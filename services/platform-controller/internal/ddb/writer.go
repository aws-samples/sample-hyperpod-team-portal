// Package ddb 把派生出的状态写入 DynamoDB ResourceIndex 表。
//
// 对应 Python services/platform-api/app/repositories/resource_index.py:
//   - update_status_if_changed / _build_status_update_expr (部分更新 + dedup + active_ws 联动)
//   - mark_deleted (收到 CR DELETED)
//
// 核心约束 (与 Python 同口径):
//   - UpdateItem 部分更新: 只 SET metadata.<派生字段>, 绝不 PutItem 整行 (保护业务字段)
//   - dedup: rv 增长 且 _DEDUP_FIELDS 任一变 才写 (避免每秒空转)
//   - kueue_status 冻结 (空串): 既不 SET ks 也不动 active_ws (保持旧值)
//   - active_ws 联动 (稀疏 GSI): Set→SET=ws_id; Remove→REMOVE; Freeze→不动
//   - 主键: workspace_id (PK) + resource_key = "<resource_type>#<resource_id>" (SK)
package ddb

import (
	"context"
	"errors"
	"log"
	"strconv"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/derive"
)

// Writer 封装对 ResourceIndex 表的写入。
type Writer struct {
	client *dynamodb.Client
	table  string
	// DryRun: true 时 UpsertStatus/MarkDeleted 只 log 不真写 (首次验证派生逻辑用)。
	DryRun bool
}

func New(client *dynamodb.Client, table string) *Writer {
	return &Writer{client: client, table: table}
}

// Target 标识要写的那一行 (主键 + 类型 + rv)。
type Target struct {
	WorkspaceID     string // PK
	ResourceType    string // train / inference / dev (resource_key 前缀)
	ResourceID      string // resource_key 后缀
	ResourceVersion int64  // CR 的 metadata.resourceVersion (dedup 用 rv 增长判定)
}

func (t Target) resourceKey() string { return t.ResourceType + "#" + t.ResourceID }

// _DEDUP_FIELDS: 任一相对 DDB 现值变化 (且 rv 增长) 才写 (对应 Python)。
// 含 kueue_status (仅当本次有确定值时); 不含 last_condition_message (高频变, phase 不变时不应触发写)。
// started_at/ended_at 不在基础集: 仅 OwnsLifecycleTimes 类型 (训练/开发机) 才纳入 (见 buildUpsert),
// 服务类这俩由 Python 写, controller 不比不写。
var dedupFields = []string{"phase", "priority_class", "status_detail"}

// buildUpsert 组装 UpdateItem 的表达式 (供测试)。
// 注: LwsDeleted 或 GatewayDeleted 时注入 time.Now(), 非纯函数; 测试断言 :now 存在即可。
func buildUpsert(t Target, s derive.Status) (updateExpr, condExpr string,
	names map[string]string, values map[string]ddbtypes.AttributeValue) {
	names = map[string]string{
		"#md": "metadata",
		"#rv": "k8s_resource_version",
	}
	values = map[string]ddbtypes.AttributeValue{
		":rv": numAV(t.ResourceVersion),
	}
	setClauses := []string{"#md.#rv = :rv"}
	var removeClauses []string

	// 始终写的派生字段。
	strField := func(alias, field, val string) {
		names["#"+alias] = field
		values[":"+alias] = strAV(val)
		setClauses = append(setClauses, "#md.#"+alias+" = :"+alias)
	}
	strField("phase", "phase", s.Phase)
	// started_at/ended_at: 仅自派生生命周期时间戳的类型 (训练/开发机/Ray) 才写。服务类
	// (推理/llm-d/dynamo) 由 Python 停止流程写, controller 不碰 — 否则每次 reconcile 用空值
	// (→ NULL) 把 Python 写的 ended_at 抹掉, 前端运行时长永远算不对。
	//
	// ★ 值为空则不写 (而非写 NULL): 时间戳未就绪时保持"字段缺失"。关键在于让 MarkDeleted 的
	//   if_not_exists(ended_at, now) 能区分"从未结束"(属性缺失 → 补 CR 删除即停止时刻) 与
	//   "已有真实结束时刻"(保留)。若运行中写 NULL, 属性即"存在", if_not_exists 会误判为已设,
	//   停止的 RayJob ended_at 永远补不上, 前端运行时长在 stop 后仍一直往上涨。
	//   NULL 与缺失对下游 (前端 / Python _ri_to_ray) 都读作 None, 无功能差异。
	setStarted := s.OwnsLifecycleTimes && s.StartedAt != ""
	setEnded := s.OwnsLifecycleTimes && s.EndedAt != ""
	if setStarted {
		strField("started_at", "started_at", s.StartedAt)
	}
	if setEnded {
		strField("ended_at", "ended_at", s.EndedAt)
	}
	strField("lcm", "last_condition_message", s.LastConditionMessage)
	strField("pc", "priority_class", s.PriorityClass)

	// status_detail (any: 训练/推理=map, 开发机=list)。
	names["#sd"] = "status_detail"
	values[":sd"] = anyAV(s.StatusDetail)
	setClauses = append(setClauses, "#md.#sd = :sd")

	// 推理 endpoint_url (训练/开发机为空, SET 成空串无害; 与 Python 一致)。
	strField("eu", "endpoint_url", s.EndpointURL)

	// kueue_status: 仅当非冻结 (有确定值) 才 SET。
	ksPresent := s.KueueStatus != ""
	if ksPresent {
		names["#ks"] = "kueue_status"
		values[":ks"] = strAV(s.KueueStatus)
		setClauses = append(setClauses, "#md.#ks = :ks")
	}

	// ── llm-d gateway 迷你任务字段: 仅 llmd 任务带 (判据: detail 非 nil 或 gks 非空),
	//    避免给训练/推理行写 NULL gateway 列 ──
	hasGateway := s.GatewayStatusDetail != nil || s.GatewayKueueStatus != ""
	gksPresent := s.GatewayKueueStatus != ""
	if hasGateway {
		strField("gp", "gateway_phase", s.GatewayPhase)
		names["#gsd"] = "gateway_status_detail"
		values[":gsd"] = anyAV(s.GatewayStatusDetail)
		setClauses = append(setClauses, "#md.#gsd = :gsd")
		if gksPresent {
			names["#gks"] = "gateway_kueue_status"
			values[":gks"] = strAV(s.GatewayKueueStatus)
			setClauses = append(setClauses, "#md.#gks = :gks")
		}
	}

	// ── 双删除时间戳: if_not_exists 写一次 (删除进度持久化; 双双齐时 active_ws 才 Remove,
	//    见 derive_llmd)。写入放行不需独立旁路: LwsDeleted 时 ks=Finished 走 ks 旁路,
	//    GatewayDeleted 时 gks=Finished 走 gks 旁路 (搭车)。──
	if s.LwsDeleted || s.GatewayDeleted {
		values[":now"] = strAV(time.Now().UTC().Format(time.RFC3339))
	}
	if s.LwsDeleted {
		names["#lda"] = "lws_deleted_at"
		setClauses = append(setClauses, "#md.#lda = if_not_exists(#md.#lda, :now)")
	}
	if s.GatewayDeleted {
		names["#gda"] = "gateway_deleted_at"
		setClauses = append(setClauses, "#md.#gda = if_not_exists(#md.#gda, :now)")
	}

	// 顶层 active_ws 联动。
	var activeBypass string
	switch s.ActiveWS {
	case derive.ActiveSet:
		values[":aws"] = strAV(t.WorkspaceID)
		setClauses = append(setClauses, "active_ws = :aws")
		activeBypass = "attribute_not_exists(active_ws) OR active_ws <> :aws"
	case derive.ActiveRemove:
		removeClauses = append(removeClauses, "active_ws")
		activeBypass = "attribute_exists(active_ws)"
	case derive.ActiveFreeze:
		// 不动 active_ws。
	}

	updateExpr = "SET " + join(setClauses, ", ")
	if len(removeClauses) > 0 {
		updateExpr += " REMOVE " + join(removeClauses, ", ")
	}

	// ── ConditionExpression: dedup (rv 增长 AND 任一 dedup 字段变) + 旁路 ──
	// df 必须先拷贝再 append: 直接 append 到包级 dedupFields 的别名会污染全局 (潜在 bug)。
	df := append([]string{}, dedupFields...)
	fieldAlias := map[string]string{
		"phase": "phase", "started_at": "started_at", "ended_at": "ended_at",
		"priority_class": "pc", "status_detail": "sd", "kueue_status": "ks",
	}
	// started_at/ended_at 仅在本次 SET 了它们时才纳入 dedup (否则条件引用未定义的别名/值)。
	if setStarted {
		df = append(df, "started_at")
	}
	if setEnded {
		df = append(df, "ended_at")
	}
	if ksPresent {
		df = append(df, "kueue_status")
	}
	if hasGateway {
		df = append(df, "gateway_phase", "gateway_status_detail")
		fieldAlias["gateway_phase"] = "gp"
		fieldAlias["gateway_status_detail"] = "gsd"
		if gksPresent {
			df = append(df, "gateway_kueue_status")
			fieldAlias["gateway_kueue_status"] = "gks"
		}
	}
	dedupOr := make([]string, 0, len(df))
	for _, f := range df {
		a := fieldAlias[f]
		dedupOr = append(dedupOr, "attribute_not_exists(#md.#"+a+") OR #md.#"+a+" <> :"+a)
	}
	mainCond := "(attribute_not_exists(#md.#rv) OR #md.#rv < :rv) AND ( " + join(dedupOr, " OR ") + " )"

	// 补写旁路: ks 缺失 或 ks 值变化 (绕开 rv 闸门) / active_ws 失配。
	//
	// ★ ks 必须绕开"CR rv 增长"闸门: 开发机/推理是 2 跳, ks 来自 Workload 而非 CR。
	//   Workload 变化 (如 Queued→Admitted) 触发 reconcile, 但 CR 本身没变、rv 没涨,
	//   主条件的 #md.#rv < :rv 不成立 → ks 变化被挡死, DDB 永远停在旧值 (实测 bob-dev-11
	//   卡在 Queued 而集群已 Admitted)。故 ks 只要与 DDB 现值不同就放行, 不卡 rv。
	//   安全: level-based reconcile 读的是当前 cache 里 Workload 现算的 ks (非旧事件带的值),
	//   不会旧值回写。与下方 active_ws 失配旁路同理 (active_ws 也来自 ks, 早已绕开 rv)。
	var bypasses []string
	if ksPresent {
		bypasses = append(bypasses, "attribute_not_exists(#md.#ks) OR #md.#ks <> :ks")
	}
	// phase 同 ks 需绕开 rv 闸门 (ks-rv-gate-2hop-bug 的 phase 版, 实测 RayJob bob-ray-06):
	// RayJob 的 phase 来自 status.jobStatus/jobDeploymentStatus (status 子资源), 会在 CR
	// metadata.resourceVersion 不增长时变化 (尤其 jobStatus 从无到有那刻) → 被 mainCond 的
	// rv 闸门 (#md.#rv < :rv) 挡死, phase 永远卡在旧值/NULL。故 phase 只要与 DDB 现值不同就放行。
	// 安全性同 ks 旁路 (writer.go 上方 ★ 论证): level-based reconcile 读 cache 现算值, 非旧事件带的值。
	// phase 无条件 SET (strField), 恒在 #phase/:phase, 故无需 if 守卫。
	bypasses = append(bypasses, "attribute_not_exists(#md.#phase) OR #md.#phase <> :phase")
	// gateway_kueue_status 同 ks 需绕开 rv 闸门: 它来自 gateway Workload (pod 级),
	// Workload 变化时 LWS/Deployment 的 rv 都不涨 (同上方 ks 旁路的 ★ 论证)。
	if gksPresent {
		bypasses = append(bypasses, "attribute_not_exists(#md.#gks) OR #md.#gks <> :gks")
	}
	if activeBypass != "" {
		bypasses = append(bypasses, activeBypass)
	}
	condExpr = mainCond
	for _, b := range bypasses {
		condExpr = "( " + condExpr + " ) OR " + b
	}
	return updateExpr, condExpr, names, values
}

// UpsertStatus 部分更新状态字段 + active_ws 联动 (UpdateItem, 带 dedup 条件)。
// 行不存在 (ConditionalCheckFailed 因主键 attribute_not_exists) 时, 当前实现按 Python
// "absent → create_stub" 的简化版处理: 这里先 SET 主键 + 字段 (upsert 语义), 后续可拆分。
//
// 返回 nil = 写成功或被 dedup 条件挡下 (无变化, 正常); 其它 error 交 work queue 重试。
func (w *Writer) UpsertStatus(ctx context.Context, t Target, s derive.Status) error {
	updateExpr, condExpr, names, values := buildUpsert(t, s)

	if w.DryRun {
		log.Printf("[DRY_RUN] UpsertStatus key=%s/%s rv=%d ks=%q active=%v phase=%q update=%q cond=%q",
			t.WorkspaceID, t.resourceKey(), t.ResourceVersion, s.KueueStatus, s.ActiveWS, s.Phase,
			updateExpr, condExpr)
		return nil
	}

	_, err := w.client.UpdateItem(ctx, &dynamodb.UpdateItemInput{
		TableName: aws.String(w.table),
		Key: map[string]ddbtypes.AttributeValue{
			"workspace_id": strAV(t.WorkspaceID),
			"resource_key": strAV(t.resourceKey()),
		},
		UpdateExpression:          aws.String(updateExpr),
		ConditionExpression:       aws.String(condExpr),
		ExpressionAttributeNames:  names,
		ExpressionAttributeValues: values,
	})
	if err != nil {
		var ccf *ddbtypes.ConditionalCheckFailedException
		if errors.As(err, &ccf) {
			return nil // dedup 条件未满足 = 无变化, 正常 skip
		}
		return err
	}
	return nil
}

// buildMarkDeleted 组装 MarkDeleted 的 UpdateItem 表达式 (供测试)。
// 注: keepPhase=true (RayJob) 时注入 time.Now() 补 ended_at, 非纯函数; 测试断言 :now 存在即可。
func buildMarkDeleted(keepPhase bool) (updateExpr, condExpr string,
	names map[string]string, values map[string]ddbtypes.AttributeValue) {
	names = map[string]string{
		"#md": "metadata",
		"#ks": "kueue_status",
	}
	values = map[string]ddbtypes.AttributeValue{
		":finished": strAV(derive.KueueFinished),
	}
	if keepPhase {
		// RayJob: phase 不动 (终态 phase 已由 MODIFIED 事件写好, DELETED 不覆盖)。
		// 补 ended_at: 用户停止 = 删 CR, KubeRay 从没写过 status.endTime → controller 也没派生到
		// → ended_at 缺失 → 前端运行时长在 stop 后仍一直往上涨。CR 删除即 Ray 真正的终止时刻,
		// 用 if_not_exists 写 now: 正常跑完已有真实 endTime 则保留 (不被 ttl-GC 的删除时刻覆盖),
		// 停止/编排失败等 endTime 缺失时补上停止时刻。依赖 buildUpsert 空值不写 (缺失 ≠ NULL)。
		names["#ended_at"] = "ended_at"
		values[":now"] = strAV(time.Now().UTC().Format(time.RFC3339))
		updateExpr = "SET #md.#ks = :finished, #md.#ended_at = if_not_exists(#md.#ended_at, :now) REMOVE active_ws"
	} else {
		names["#phase"] = "phase"
		values[":phase"] = strAV("Stopped")
		updateExpr = "SET #md.#phase = :phase, #md.#ks = :finished REMOVE active_ws"
	}
	condExpr = "attribute_exists(workspace_id)"
	return updateExpr, condExpr, names, values
}

// MarkDeleted 收到 CR 消失 (删除/停止) 时写终态: SET metadata.kueue_status=Finished  REMOVE active_ws。
//
// keepPhase 控制是否改 phase:
//   - false (训练/推理/开发机/Dynamo): 额外 SET metadata.phase=Stopped。
//     这些类型 CR 消失≈用户删除 (训练 ttl=-1 永不 GC), 标 Stopped 语义正确。
//   - true (RayJob): phase 保持原样不动。RayJob CR 会被 ttl GC 删除 (非用户操作),
//     成功任务的 phase 已由终态 MODIFIED 事件写成 SUCCEEDED, DELETED 不能覆盖成 Stopped
//     (文档 §7 定案: phase 靠终态 MODIFIED 先落库, DELETED 只翻 active_ws)。
//     边缘: 用户在运行中删 RayJob (无终态 jobStatus 事件), 行会停在 phase=RUNNING +
//     ks=Finished + active_ws 摘除 — §7 接受的取舍 (RayJob 没有区别于 ttl GC 的可靠用户停止信号)。
//
// 不写 deleted_at: 前端 DELETE 接口已打过, 行可见性由它决定; 也不需要 stop_requested 豁免
// (不写 deleted_at, 删/停写同一套终态)。
//
// 条件 attribute_exists(workspace_id): 行必须已存在才更新, 避免删除事件凭空建 stub 行。
// ConditionalCheckFailed (行不存在) → nil (无事可做)。
func (w *Writer) MarkDeleted(ctx context.Context, ws, resourceType, resourceID string, keepPhase bool) error {
	key := resourceType + "#" + resourceID
	updateExpr, condExpr, names, values := buildMarkDeleted(keepPhase)

	if w.DryRun {
		log.Printf("[DRY_RUN] MarkDeleted key=%s/%s keepPhase=%v update=%q cond=%q", ws, key, keepPhase, updateExpr, condExpr)
		return nil
	}

	_, err := w.client.UpdateItem(ctx, &dynamodb.UpdateItemInput{
		TableName: aws.String(w.table),
		Key: map[string]ddbtypes.AttributeValue{
			"workspace_id": strAV(ws),
			"resource_key": strAV(key),
		},
		UpdateExpression:          aws.String(updateExpr),
		ConditionExpression:       aws.String(condExpr),
		ExpressionAttributeNames:  names,
		ExpressionAttributeValues: values,
	})
	if err != nil {
		var ccf *ddbtypes.ConditionalCheckFailedException
		if errors.As(err, &ccf) {
			return nil // 行不存在 = 无事可做
		}
		return err
	}
	return nil
}

// ── AttributeValue 辅助 ──

func strAV(s string) ddbtypes.AttributeValue {
	if s == "" {
		return &ddbtypes.AttributeValueMemberNULL{Value: true} // 空 → NULL (与 Python 写 None 一致)
	}
	return &ddbtypes.AttributeValueMemberS{Value: s}
}

func numAV(n int64) ddbtypes.AttributeValue {
	return &ddbtypes.AttributeValueMemberN{Value: strconv.FormatInt(n, 10)}
}

func mapAV(m map[string]any) ddbtypes.AttributeValue {
	if len(m) == 0 {
		return &ddbtypes.AttributeValueMemberNULL{Value: true}
	}
	mm := make(map[string]ddbtypes.AttributeValue, len(m))
	for k, v := range m {
		mm[k] = anyAV(v)
	}
	return &ddbtypes.AttributeValueMemberM{Value: mm}
}

// anyAV 把任意 JSON 值 (来自 unstructured status) 转 DDB AttributeValue (递归)。
func anyAV(v any) ddbtypes.AttributeValue {
	switch x := v.(type) {
	case nil:
		return &ddbtypes.AttributeValueMemberNULL{Value: true}
	case string:
		if x == "" {
			return &ddbtypes.AttributeValueMemberS{Value: ""} // status_detail 内部空串保留为 S
		}
		return &ddbtypes.AttributeValueMemberS{Value: x}
	case bool:
		return &ddbtypes.AttributeValueMemberBOOL{Value: x}
	case int64:
		return &ddbtypes.AttributeValueMemberN{Value: strconv.FormatInt(x, 10)}
	case float64:
		return &ddbtypes.AttributeValueMemberN{Value: strconv.FormatFloat(x, 'f', -1, 64)}
	case map[string]any:
		mm := make(map[string]ddbtypes.AttributeValue, len(x))
		for k, vv := range x {
			mm[k] = anyAV(vv)
		}
		return &ddbtypes.AttributeValueMemberM{Value: mm}
	case []any:
		ll := make([]ddbtypes.AttributeValue, len(x))
		for i, vv := range x {
			ll[i] = anyAV(vv)
		}
		return &ddbtypes.AttributeValueMemberL{Value: ll}
	default:
		return &ddbtypes.AttributeValueMemberNULL{Value: true}
	}
}

func join(parts []string, sep string) string {
	out := ""
	for i, p := range parts {
		if i > 0 {
			out += sep
		}
		out += p
	}
	return out
}
