package derive

import (
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// llm-d (LWS + gateway Deployment 双资源任务) 派生。
//
// 与四类现有任务的关键差异:
//   - 双资源: 主状态锚 LWS, gateway 为对称迷你任务 (独立四字段, 不混主状态)。
//   - phase = LWS condition 原样 (Available/Progressing 互斥, 取 True 的那个);
//     实证: 刚创建只有 Progressing 一条, Available 可能整个缺席 (非 False) → 取不到给空串冻结。
//     仅 Stopped 平台自加 (LWS 已删)。
//   - kueue_status = N 个 LWS Workload 聚合【取最好】(aggregateKueueBest, 冗余关系 OR 语义)。
//     LWS 删 → Finished (平台自加)。
//   - LWS/Deployment 各自 List 为空 = 各自的删除信号 (LWS 无自行终止路径, 删除是唯一终态);
//     置 LwsDeleted/GatewayDeleted → writer 写 *_deleted_at (if_not_exists)。
//   - active_ws: 双删 → Remove; LWS 在且聚合活跃 → Set; 其余 (含半删态) → Freeze
//     (半删态不摘 = 幸存资源仍占配额, 泄漏显性化, 刻意不加清扫)。

func deriveLlmd(in Inputs) Status {
	var s Status

	// ── 主状态 (LWS) ──
	if in.LWS != nil {
		s.Phase = lwsPhase(in.LWS)
		s.StatusDetail = statusDetail(in.LWS)
		s.PriorityClass = crLabel(in.LWS, labelPriorityClass)
		s.KueueStatus = aggregateKueueBest(in.Workloads) // "" = 冻结
	} else {
		s.Phase = "Stopped"
		s.KueueStatus = KueueFinished
		s.LwsDeleted = true
	}

	// ── gateway 迷你任务 ──
	if in.GatewayDeploy != nil {
		s.GatewayPhase = deployPhase(in.GatewayDeploy)
		s.GatewayStatusDetail = statusDetail(in.GatewayDeploy)
		s.GatewayKueueStatus = aggregateKueueBest(in.GatewayWorkloads)
		s.EndpointURL = llmdEndpointURL(in.GatewayDeploy)
	} else {
		s.GatewayKueueStatus = KueueFinished
		s.GatewayDeleted = true
	}

	// ── active_ws: 双 deleted 才 Remove ──
	switch {
	case s.LwsDeleted && s.GatewayDeleted:
		s.ActiveWS = ActiveRemove
	case in.LWS != nil && IsActive(s.KueueStatus):
		s.ActiveWS = ActiveSet
	default:
		s.ActiveWS = ActiveFreeze // Workload 空集 / 半删态
	}
	return s
}

// lwsPhase: LWS conditions 里取 status==True 的 type。Available/Progressing 由 LWS
// controller 保证互斥; UpdateInProgress 可与 Progressing 并存, 优先报 Progressing
// (完整 conditions 在 status_detail)。无 True condition (刚创建) → 空串。
func lwsPhase(lws *unstructured.Unstructured) string {
	trueTypes := trueConditionTypes(lws)
	for _, t := range []string{"Available", "Progressing", "UpdateInProgress"} {
		if trueTypes[t] {
			return t
		}
	}
	return ""
}

// deployPhase: gateway Deployment condition, Available=True 优先 (稳态 Progressing 恒
// True 是 Deployment 特性, 语义弱)。都取不到 → 空串。
// (无 UpdateInProgress: Deployment 无此 condition 类型, 勿从 lwsPhase 照搬。)
func deployPhase(d *unstructured.Unstructured) string {
	trueTypes := trueConditionTypes(d)
	for _, t := range []string{"Available", "Progressing"} {
		if trueTypes[t] {
			return t
		}
	}
	return ""
}

// trueConditionTypes: status.conditions 里 status==True 的 type 集合。
func trueConditionTypes(obj *unstructured.Unstructured) map[string]bool {
	conds, _, _ := unstructured.NestedSlice(obj.Object, "status", "conditions")
	out := map[string]bool{}
	for _, c := range conds {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		if st, _ := m["status"].(string); st == "True" {
			if t, _ := m["type"].(string); t != "" {
				out[t] = true
			}
		}
	}
	return out
}

// llmdEndpointURL: gateway Service 与 Deployment 同名 (平台创建约定, 实证), 端口 30000。
func llmdEndpointURL(d *unstructured.Unstructured) string {
	name := d.GetName()
	ns := d.GetNamespace()
	if name == "" || ns == "" {
		return ""
	}
	return "http://" + name + "." + ns + ".svc.cluster.local:30000"
}
