package derive

import (
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// Dynamo (DynamoGraphDeployment CR) 派生。
//
// 与训练/推理/开发机的关键差异 (官方 CRD + 真集群 hyperpod-ns-demo 实测确认):
//   - phase = status.state (4 态: initializing/pending/successful/failed), 原样不归一化。
//   - 一个 DGD 对应【多个】Kueue Workload (每 Pod 一个, owner=Pod), 而非 1 CR≈1 Workload。
//     故 kueue_status = 多 Workload【聚合】取最落后 (aggregateKueue); 关联走 fetchWorkloads(复数)。
//   - status_detail = DGD 原始 status (state/components/conditions 原样), 与训练/推理/开发机对称。
//   - kueue_status 聚合【封顶 Admitted】: 实测 Dynamo Workload 只有 QuotaReserved+Admitted,
//     永不自行 Finished。任务结束是 Pod/Workload 被【删除】, 聚合空集合得 "" (非 Finished)。
//   - 故 Finished 由"全部 Pod 消失 + phase 终态"判 (见下), 而非聚合得来。
//
// active_ws (是否还占资源):
//   - Workload 非空: is_active(聚合 ks) ? Set : Remove (聚合活跃态一律 Set)。
//   - Workload 空 (Pod/Workload 已删或还没建):
//       * 有 Running/Pending Pod → 过渡态 (拆一半/刚建), 冻结。
//       * 0 Pod 且 phase==failed → 真终态: Finished + Remove。
//       * 0 Pod 且 phase 非 failed (initializing/pending/successful) → startup 窗口或异常, 冻结。
//   - 用户主动 stop/删除 = 删 CR → 走 reconciler.handleDeleted → MarkDeleted (phase=Stopped,
//     ks=Finished, 删 active_ws), 不经本派生逻辑。
//
// ⚠️ "0 Pod + phase==failed → Finished" 是【待实测占位】: 至今未观察过真实 failed DGD,
//   不确定 failed 是否稳定终态 / 会否自愈 / Pod 是否真被清。占位安全性: 若 failed 会自愈,
//   最坏是短暂标 Finished, 下次 reconcile (pod 重建) 自动改回活跃; startup 不命中 (phase 非 failed)。

// dynamoPhaseFailed: Dynamo 的终态 phase (仅 failed; successful 是长期运行服务态, 非终态)。
const dynamoPhaseFailed = "failed"

func deriveDynamo(in Inputs) Status {
	cr := in.CR
	conds := crConditions(cr)
	phase, _, _ := unstructured.NestedString(cr.Object, "status", "state")

	s := Status{
		Phase:                phase, // status.state 原样
		LastConditionMessage: lastMessage(conds),
		PriorityClass:        crLabel(cr, labelPriorityClass),
		StatusDetail:         statusDetail(cr), // DGD 原始 status 整段
		// started_at / ended_at 留空 (推理服务无对应 condition 时间语义)。
	}

	// 有 Workload: 聚合取最落后 (封顶 Admitted)。
	if ks := aggregateKueue(in.Workloads); ks != "" {
		s.KueueStatus = ks
		if IsActive(ks) {
			s.ActiveWS = ActiveSet
		} else {
			s.ActiveWS = ActiveRemove
		}
		return s
	}

	// 无 Workload: 据 Pod / phase 判终态或冻结。
	if dynamoHasLivePod(in.DynamoPods) {
		// 有存活 Pod: 过渡态 (Workload 还没建 / 正在拆一半), 冻结保持 DDB 旧值。
		s.KueueStatus = ""
		s.ActiveWS = ActiveFreeze
		return s
	}
	// 0 Pod:
	if phase == dynamoPhaseFailed {
		// 真终态 (失败且 Pod 已清)。
		s.KueueStatus = KueueFinished
		s.ActiveWS = ActiveRemove
		return s
	}
	// 0 Pod 但 phase 非 failed (startup 窗口: 刚建, Pod 还没起) → 冻结, 别误判 Finished。
	s.KueueStatus = ""
	s.ActiveWS = ActiveFreeze
	return s
}

// dynamoHasLivePod: 该 DGD 有没有 Running/Pending 的 Pod (占着资源)。
func dynamoHasLivePod(pods []*unstructured.Unstructured) bool {
	for _, p := range pods {
		phase, _, _ := unstructuredString(p, "status", "phase")
		if phase == "Running" || phase == "Pending" {
			return true
		}
	}
	return false
}
