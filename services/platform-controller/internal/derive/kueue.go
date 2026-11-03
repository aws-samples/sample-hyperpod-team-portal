// Package derive 内的 Kueue 六态常量 + 从 Workload 派生六态。
// 对应 Python services/platform-api/app/modules/shared/kueue_status.py。
package derive

import "k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

// 六态 (Workload condition type 名)。
const (
	KueueQueued        = "Queued"
	KueueQuotaReserved = "QuotaReserved"
	KueueAdmitted      = "Admitted"
	KueuePodsReady     = "PodsReady"
	KueueEvicted       = "Evicted"
	KueueFinished      = "Finished"
)

// 取态固定优先级 (从高到低, 取第一个 status==True 的 condition type)。
var kueuePriority = []string{
	KueueFinished, KueueEvicted, KueuePodsReady, KueueAdmitted, KueueQuotaReserved,
}

// 活跃集: 非终态 (前 5 态全活跃, 含 Evicted)。
var activeStates = map[string]bool{
	KueueQueued: true, KueueQuotaReserved: true, KueueAdmitted: true,
	KueuePodsReady: true, KueueEvicted: true,
}

// IsActive: 六态除 Finished 外都活跃 (空串=未知, 非活跃)。
func IsActive(ks string) bool { return activeStates[ks] }

// IsTerminal: 只有 Finished 是终态。
func IsTerminal(ks string) bool { return ks == KueueFinished }

// deriveKueueFromWorkload 从单个 Workload 派生六态 (纯固定优先级)。
//   - workload=nil → 返回 "" (调用方按 CR 状态决定 Finished 或冻结)
//   - 有 condition status==True → 按 kueuePriority 取最高的 type
//   - 全 False / 缺失 (排队中) → 兜底 Queued
func deriveKueueFromWorkload(wl *unstructured.Unstructured) string {
	if wl == nil {
		return ""
	}
	conds, _, _ := unstructured.NestedSlice(wl.Object, "status", "conditions")
	trueTypes := map[string]bool{}
	for _, c := range conds {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		if status, _ := m["status"].(string); status == "True" {
			if t, _ := m["type"].(string); t != "" {
				trueTypes[t] = true
			}
		}
	}
	for _, t := range kueuePriority {
		if trueTypes[t] {
			return t
		}
	}
	return KueueQueued
}

// kueueRank: 六态"进展度"分数, 越大越靠前 (就绪)。用于聚合取最落后。
// 顺序: Queued(最落后) < QuotaReserved < Admitted < PodsReady < Evicted < Finished。
// (Evicted/Finished 理论上聚合里少见 — Dynamo Workload 封顶 Admitted, 不自行 Finished。)
var kueueRank = map[string]int{
	KueueQueued: 0, KueueQuotaReserved: 1, KueueAdmitted: 2,
	KueuePodsReady: 3, KueueEvicted: 4, KueueFinished: 5,
}

// kueueRankBest: "取最好" 用的进展序, 与 kueueRank 的关键差异是 Evicted 沉底 —
// 被踢的副本是最差的, 不能沿用 kueueRank(Evicted=4) 反向取 max, 否则一个被抢占的
// 副本会把整个任务顶成 Evicted。Finished 仍最高 (终态即最终进展)。
var kueueRankBest = map[string]int{
	KueueEvicted: 0, KueueQueued: 1, KueueQuotaReserved: 2,
	KueueAdmitted: 3, KueuePodsReady: 4, KueueFinished: 5,
}

// aggregateKueueBest 把【冗余关系】(多副本互为备份, OR 语义) 的多个 Workload 聚合成
// 单一六态 —— 取【最好】: 一个副本好 = 服务可用, 其余排队只是容量降级 (容量信息由
// readyReplicas/replicas 另行展示)。适用: 单机推理多副本 / llm-d 多 replica group。
// 对比 aggregateKueue (组成关系, AND 语义, 取最落后): 聚合方向按 Workload 拓扑关系定。
//
// 空集合返回 "" (冻结信号, 语义同 aggregateKueue)。
func aggregateKueueBest(workloads []*unstructured.Unstructured) string {
	best := ""
	bestRank := -1
	for _, wl := range workloads {
		ks := deriveKueueFromWorkload(wl)
		if ks == "" {
			continue
		}
		if r, ok := kueueRankBest[ks]; ok && r > bestRank {
			best, bestRank = ks, r
		}
	}
	return best
}

// aggregateKueue 把一个 DGD 的多个 Workload 聚合成单一六态 —— 取【最落后】(木桶短板):
// 只要有一个还在排队/等配额, 整个任务就未就绪。全部 Admitted 才算就绪。
//
// 空集合返回 "" (冻结信号: 无 Workload 时由派生层据 Pod / phase 判 Finished 或冻结,
// 因 Dynamo Workload 不自行 Finished, 结束是被删除 → 聚合得不到 Finished, 见 derive_dynamo)。
func aggregateKueue(workloads []*unstructured.Unstructured) string {
	worst := ""
	worstRank := 1 << 30
	for _, wl := range workloads {
		ks := deriveKueueFromWorkload(wl)
		if ks == "" {
			continue
		}
		if r, ok := kueueRank[ks]; ok && r < worstRank {
			worst, worstRank = ks, r
		}
	}
	return worst
}
