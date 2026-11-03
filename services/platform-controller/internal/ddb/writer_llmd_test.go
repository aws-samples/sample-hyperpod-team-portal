package ddb

import (
	"sort"
	"strings"
	"testing"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/derive"
)

// resolveNames 把表达式里的 #alias 还原成真实字段名 (buildUpsert 全走别名, 断言可读性用)。
// 按 alias 长度降序替换, 避免前缀撞车 (如 #gks vs #gk)。
func resolveNames(expr string, names map[string]string) string {
	aliases := make([]string, 0, len(names))
	for a := range names {
		aliases = append(aliases, a)
	}
	sort.Slice(aliases, func(i, j int) bool { return len(aliases[i]) > len(aliases[j]) })
	for _, a := range aliases {
		expr = strings.ReplaceAll(expr, a, names[a])
	}
	return expr
}

func TestBuildUpsertLlmdFields(t *testing.T) {
	tgt := Target{WorkspaceID: "ws1", ResourceType: "llmd", ResourceID: "id-123", ResourceVersion: 7}

	t.Run("llmd 任务: gateway 三字段 SET + gks 旁路进条件", func(t *testing.T) {
		s := derive.Status{
			Phase: "Available", KueueStatus: "Admitted", ActiveWS: derive.ActiveSet,
			GatewayPhase: "Available", GatewayKueueStatus: "Admitted",
			GatewayStatusDetail: map[string]any{"readyReplicas": int64(2)},
		}
		update, cond, names, _ := buildUpsert(tgt, s)
		update = resolveNames(update, names)
		for _, want := range []string{"gateway_phase", "gateway_kueue_status", "gateway_status_detail"} {
			if !strings.Contains(update, want) {
				t.Errorf("update 应含 %s: %s", want, update)
			}
		}
		if !strings.Contains(cond, "#gks") {
			t.Errorf("cond 应含 gateway ks 旁路: %s", cond)
		}
	})

	t.Run("非 llmd (无 gateway 字段) 不写 gateway 列", func(t *testing.T) {
		s := derive.Status{Phase: "Running", KueueStatus: "Admitted", ActiveWS: derive.ActiveSet}
		update, _, names, _ := buildUpsert(tgt, s)
		update = resolveNames(update, names)
		if strings.Contains(update, "gateway") {
			t.Errorf("非 llmd 不应写 gateway 字段: %s", update)
		}
	})

	t.Run("gks 冻结 (空串): gateway_kueue_status 不 SET", func(t *testing.T) {
		s := derive.Status{Phase: "Available", KueueStatus: "Admitted", ActiveWS: derive.ActiveSet,
			GatewayPhase: "Progressing", GatewayStatusDetail: map[string]any{"replicas": int64(1)}}
		update, _, names, _ := buildUpsert(tgt, s)
		update = resolveNames(update, names)
		if strings.Contains(update, "gateway_kueue_status") {
			t.Errorf("gks 空串应冻结不写: %s", update)
		}
		if !strings.Contains(update, "gateway_phase") {
			t.Errorf("gateway_phase 仍应写: %s", update)
		}
	})

	t.Run("服务类 (OwnsLifecycleTimes=false): 不写 started_at/ended_at, 条件也不引用", func(t *testing.T) {
		// llm-d 停止后终态: Python 已写 ended_at, controller 必须不碰这俩字段, 否则抹回 NULL。
		s := derive.Status{
			Phase: "Stopped", KueueStatus: "Finished", GatewayKueueStatus: "Finished",
			LwsDeleted: true, GatewayDeleted: true, ActiveWS: derive.ActiveRemove,
		}
		update, cond, names, values := buildUpsert(tgt, s)
		update = resolveNames(update, names)
		cond = resolveNames(cond, names)
		if strings.Contains(update, "started_at") || strings.Contains(update, "ended_at") {
			t.Errorf("服务类不应 SET started_at/ended_at: %s", update)
		}
		if strings.Contains(cond, "started_at") || strings.Contains(cond, "ended_at") {
			t.Errorf("服务类 dedup 条件不应引用 started_at/ended_at: %s", cond)
		}
		if _, ok := values[":started_at"]; ok {
			t.Error("不应有 :started_at 值")
		}
		if _, ok := values[":ended_at"]; ok {
			t.Error("不应有 :ended_at 值")
		}
	})

	t.Run("自派生类 (OwnsLifecycleTimes=true): 非空才 SET; 空值不写 (缺失 ≠ NULL)", func(t *testing.T) {
		// 运行中: startedAt 有值, endedAt 空 → 只写 started_at, 不写 ended_at (让 MarkDeleted
		// 的 if_not_exists 能区分未结束/已结束, 见 writer.go)。
		s := derive.Status{
			Phase: "Running", KueueStatus: "Admitted", ActiveWS: derive.ActiveSet,
			StartedAt: "2026-08-24T00:00:00Z", OwnsLifecycleTimes: true,
		}
		update, cond, names, values := buildUpsert(tgt, s)
		rUpdate := resolveNames(update, names)
		if !strings.Contains(rUpdate, "started_at") {
			t.Errorf("startedAt 非空应 SET started_at: %s", rUpdate)
		}
		if strings.Contains(rUpdate, "ended_at") {
			t.Errorf("endedAt 空不应 SET ended_at (应保持缺失非 NULL): %s", rUpdate)
		}
		if _, ok := values[":ended_at"]; ok {
			t.Error("endedAt 空不应有 :ended_at 值")
		}
		if strings.Contains(resolveNames(cond, names), "ended_at") {
			t.Errorf("endedAt 空时 dedup 条件不应引用 ended_at")
		}

		// 终态: 两者都有值 → 都写。
		term := derive.Status{
			Phase: "SUCCEEDED", KueueStatus: "Finished", ActiveWS: derive.ActiveRemove,
			StartedAt: "2026-08-24T00:00:00Z", EndedAt: "2026-08-24T01:00:00Z",
			OwnsLifecycleTimes: true,
		}
		tUpdate, _, tNames, _ := buildUpsert(tgt, term)
		tUpdate = resolveNames(tUpdate, tNames)
		for _, want := range []string{"started_at", "ended_at"} {
			if !strings.Contains(tUpdate, want) {
				t.Errorf("两者非空应 SET %s: %s", want, tUpdate)
			}
		}
	})

	t.Run("deleted 标记 → if_not_exists 写一次", func(t *testing.T) {
		s := derive.Status{Phase: "Stopped", KueueStatus: "Finished",
			GatewayKueueStatus: "Finished",
			LwsDeleted:         true, GatewayDeleted: true, ActiveWS: derive.ActiveRemove}
		update, _, _, values := buildUpsert(tgt, s)
		if !strings.Contains(update, "if_not_exists(#md.#lda") ||
			!strings.Contains(update, "if_not_exists(#md.#gda") {
			t.Errorf("deleted_at 应 if_not_exists 写: %s", update)
		}
		if _, ok := values[":now"]; !ok {
			t.Error("values 应含 :now 时间戳")
		}
	})
}

// TestBuildUpsert_PhaseBypassesRvGate: phase 旁路绕开 rv 闸门 (ks-rv-gate-2hop-bug 的 phase 版,
// 实测 RayJob bob-ray-06 phase 卡 NULL)。断言 condExpr 含 phase 旁路, 并回归守卫 ks 旁路仍在。
func TestBuildUpsert_PhaseBypassesRvGate(t *testing.T) {
	tgt := Target{WorkspaceID: "ws1", ResourceType: "train", ResourceID: "bob-ray-06", ResourceVersion: 76296772}
	s := derive.Status{Phase: "Suspended (Deploy Status)", KueueStatus: "Queued", ActiveWS: derive.ActiveSet}
	_, cond, _, _ := buildUpsert(tgt, s)
	// phase 出现两次才证明旁路存在: 一次在 mainCond 的 dedup 从句 (phase ∈ dedupFields),
	// 一次在 rv 旁路。只查 Contains 会 vacuous (dedup 那次恒在), 故必须 count >= 2。
	if n := strings.Count(cond, "#md.#phase <> :phase"); n < 2 {
		t.Errorf("cond 应含 phase 旁路 (dedup + 旁路共 2 次), 实得 %d 次: %s", n, cond)
	}
	// 回归守卫: 既有 ks 旁路仍在 (同理 ks ∈ dedupFields, 也须 count >= 2)。
	if n := strings.Count(cond, "#md.#ks <> :ks"); n < 2 {
		t.Errorf("cond 仍应含 ks 旁路 (dedup + 旁路共 2 次), 实得 %d 次: %s", n, cond)
	}
}
