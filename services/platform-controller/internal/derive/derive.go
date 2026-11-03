// Package derive 把 K8s 对象 (CR + 关联 Workload) 派生成要写入 DDB 的状态。
//
// 对应现有 Python:
//   - worker/phase.py            (derive_phase / pick_single_phase)
//   - shared/kueue_status.py     (derive_kueue_status_from_workload / is_active / is_terminal)
//   - 三个 informer 的 derive_status_md
//
// 设计决策已定稿 (六态优先级 / CR 终态短路 / 训练 occupying 决策表 / 中间态冻结)。
// 训练在 derive_training.go, 开发机在 derive_dev.go, 推理在 derive_inference.go。
package derive

import (
	"context"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// ActiveDecision: 对顶层 active_ws (稀疏 GSI) 的处置。
type ActiveDecision int

const (
	ActiveFreeze ActiveDecision = iota // 不动 (保持 DDB 旧值): 中间态 / ks 未确定
	ActiveSet                          // SET active_ws = workspace_id (活跃)
	ActiveRemove                       // REMOVE active_ws (非活跃)
)

// String 让 active_ws 决策在结构化日志里可读 (否则打成裸 int, 排查 occupying 时看不懂)。
func (d ActiveDecision) String() string {
	switch d {
	case ActiveFreeze:
		return "Freeze"
	case ActiveSet:
		return "Set"
	case ActiveRemove:
		return "Remove"
	default:
		return "Unknown"
	}
}

// Status 是派生出的、要写进 DDB 的状态字段集 (只含派生字段, 不碰业务字段)。
type Status struct {
	Phase string

	// OwnsLifecycleTimes: 该类型的 started_at/ended_at 由 controller 从 CR 终态 condition 派生
	// (训练/开发机 = true)。服务类 (推理/llm-d/dynamo) 无自然终态、停止是纯人为动作, 这俩由
	// Python 停止流程写、controller 不碰 (false); 写入层据此决定是否 SET/比对这两字段, 避免每次
	// reconcile 用空值把 Python 写的 ended_at 抹成 NULL (前端运行时长因此永远算不对)。
	OwnsLifecycleTimes bool
	StartedAt          string
	EndedAt            string

	LastConditionMessage string
	PriorityClass        string

	// 六态之一; 空串 = 冻结 (查不到 Workload 且 CR 非终态 / 中间态) → 写入层不写该字段, 保持旧值。
	KueueStatus string

	// 推理/llm-d 使用: endpoint 调用地址 (训练/开发机为空; llm-d 从 gateway Service 拼)。
	EndpointURL string

	// status_detail: 原始 status 片段 (debug 弹窗); 各类结构不同 —
	// 训练=整个 status(map), 推理={state,conditions,deploymentStatus}(map),
	// 开发机=status==True 的 condition 数组(list)。故用 any 兼容, 且与 Python 写入结构一致。
	StatusDetail any

	// ── llm-d 专用: gateway 迷你任务四字段 + 双删除标记 ──
	GatewayPhase        string // gateway Deployment condition 原样 (Available/Progressing)
	GatewayKueueStatus  string // gateway Workloads 聚合取最好; Deployment 删 → Finished
	GatewayStatusDetail any    // gateway Deployment status 整段
	LwsDeleted          bool   // LWS List 为空 → writer 写 lws_deleted_at (if_not_exists)
	GatewayDeleted      bool   // gateway Deployment List 为空 → 写 gateway_deleted_at

	// 顶层 active_ws 的处置 (Set/Remove/Freeze)。
	ActiveWS ActiveDecision
}

// PodLister 让 derive 在需要判 occupying 时按 label 查 Pod (训练用)。
// 由 reconciler 注入 (用直连 API 的 client, 不 watch Pod)。返回该 CR 名下的 Pod 列表。
type PodLister func(ctx context.Context, namespace, labelSelector string) ([]*unstructured.Unstructured, error)

// Inputs 是派生所需的输入。
type Inputs struct {
	CR       *unstructured.Unstructured
	Workload *unstructured.Unstructured // 单个关联 Workload (训练/推理/开发机; nil = 查不到)
	Pods     PodLister                  // 按需查 Pod (训练 occupying 用); 可为 nil (则视作无存活 Pod)

	// RayCluster: 该 RayJob 的 RayCluster (KubeRay 派生, head+worker Pod 的 owner)。
	// nil = 已删 (ttl 到期 shutdown, 级联删 Pod) 或还没建。仅 RayJob 用: 终态时据它是否
	// 存在判 occupying —— 存在=Pod 仍在 ttl 窗口占 GPU, 不在=资源已释放 (bob-ray-12 实测)。
	RayCluster *unstructured.Unstructured

	// ── Dynamo / llm-d 共用 (多 Workload 聚合) ──
	// 由 reconciler 一次 cache 查询备齐 (Dynamo Pod 在 cache 内, 不同于训练的直连 API):
	Workloads  []*unstructured.Unstructured // Dynamo: 经 Pod uid join; llm-d: LWS 的 N 个组 Workload (ownerRef 过滤)
	DynamoPods []*unstructured.Unstructured // 该 DGD 全部 Pod; 供 workload 空时判 live pod / 终态

	// ── llm-d 专用 (双资源任务; Workloads 复用为 LWS 的 N 个 Workload) ──
	LWS              *unstructured.Unstructured   // nil = 已删 (List by llmd-id 为空)
	GatewayDeploy    *unstructured.Unstructured   // nil = 已删
	GatewayWorkloads []*unstructured.Unstructured // gateway Pod 的 pod 级 Workload
}

// Derive 按 CR 类型分派。当前仅训练已实现。
func Derive(ctx context.Context, crKind string, in Inputs) Status {
	switch crKind {
	case gvk.Training.Kind:
		return deriveTraining(ctx, in)
	case gvk.DevInstance.Kind:
		return deriveDev(in)
	case gvk.Inference.Kind:
		return deriveInference(in)
	case gvk.DynamoGraph.Kind:
		return deriveDynamo(in)
	case gvk.LlmdLWS.Kind:
		return deriveLlmd(in)
	case gvk.RayJob.Kind:
		return deriveRay(in)
	default:
		return Status{ActiveWS: ActiveFreeze}
	}
}
