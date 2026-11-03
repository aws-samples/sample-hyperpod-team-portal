package derive

import "k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

// Ray jobStatus 终态集 (来自 CR status.jobStatus, KubeRay 透传 Ray dashboard job status)。
// SUCCEEDED/FAILED = entrypoint 退出; STOPPED = 主动停止。见文档 §3b。
var rayTerminalJobStatus = map[string]bool{
	"SUCCEEDED": true,
	"FAILED":    true,
	"STOPPED":   true,
}

// jobDeploymentStatus 终态集 (编排线终态; 用于 jobStatus 为空时兜底判终态 —— 编排失败 jobStatus 永空)。
var rayTerminalDeployStatus = map[string]bool{
	"Complete": true,
	"Failed":   true,
}

// rayJobStatus 取 CR status.jobStatus (大写)。
func rayJobStatus(cr *unstructured.Unstructured) string {
	s, _, _ := unstructuredString(cr, "status", "jobStatus")
	return s
}

// rayDeployStatus 取 CR status.jobDeploymentStatus (KubeRay 编排状态: New/Suspended/Initializing/Running/Complete/Failed)。
func rayDeployStatus(cr *unstructured.Unstructured) string {
	s, _, _ := unstructuredString(cr, "status", "jobDeploymentStatus")
	return s
}

// deriveRay 实现 RayJob 的派生 (文档 §7 + 实测修正)。
//
// 实测发现 status.jobStatus 在 admitted 前 (Suspended/Initializing/queuing) 全空, 仅在 Kueue 准入且 Ray head
// 起来后才变 PENDING; 更关键: 编排失败 (配额超时/拉镜像/EFA) 时 jobDeploymentStatus=Failed 但 jobStatus 永远为空,
// 单看 jobStatus 永远判不出终态 → active_ws 永不摘除。故 phase 必须由两维度合成:
//   - jobStatus 非空 → phase=jobStatus (原样大写), 终态完全以 jobStatus ∈ {SUCCEEDED,FAILED,STOPPED} 为准
//     (权威业务成败, 此时不看 deployStatus, 防两维度打架)。
//   - jobStatus 空 → phase="{jobDeploymentStatus} (Deploy Status)" (带来源标注后缀), 终态完全以
//     jobDeploymentStatus ∈ {Complete,Failed} 为准 (编排线兜底)。两维度永不同时参与终态判定。
//   - 两者都空 → phase="" 非终态。
//
// " (Deploy Status)" 后缀故意保留, 前端在 badge/终态匹配前会剥离 (另任务), 用于告诉用户"这是编排状态非业务状态"。
//
// kueue_status 复用 deriveKueueFromWorkload; active_ws 按终态决定 (Set/Remove/Freeze)。
//
// active_ws 终态 occupying (bob-ray-12 实测修正, 推翻文档 §7 "不监听 RayCluster"):
// ttl(关闭 timeout) 到期时 KubeRay 只删 RayCluster (级联删 head+worker Pod), 而 RayJob CR
// + Workload 永久留存。故 CR 终态 / Workload.Finished 只表示"业务结束", 不表示"资源已释放"
// —— 期间 Pod 仍在 ttl 窗口占 GPU。真正的资源释放信号是 RayCluster 被删。
// 因此终态时不再无脑 Remove, 而是据 in.RayCluster 是否存在判 occupying (rayOccupyingActive)。
// RayCluster 经 setup.go 的 Owns(RayCluster) 入 cache 且其删除事件触发 reconcile 及时翻 active_ws。
func deriveRay(in Inputs) Status {
	cr := in.CR
	jobStatus := rayJobStatus(cr)
	deployStatus := rayDeployStatus(cr)

	// 合成 phase (实测修正): jobStatus 在 admitted 前全空, 且编排失败时 jobStatus 永空。
	// jobStatus 非空 → 完全以 jobStatus 为准 (权威业务成败); 空 → 回退 deployStatus 并标注来源。
	// 两维度永不同时参与终态判定 (防打架)。
	var phase string
	var terminal bool
	if jobStatus != "" {
		phase = jobStatus
		terminal = rayTerminalJobStatus[jobStatus]
	} else if deployStatus != "" {
		phase = deployStatus + " (Deploy Status)"
		terminal = rayTerminalDeployStatus[deployStatus]
	}
	// (都空 → phase="" 且 terminal=false)

	// OwnsLifecycleTimes=true: RayJob 有自然终态, started_at/ended_at 直接取 CR status 里
	// KubeRay 维护的真实开始/结束时刻 (status.startTime/endTime), 由 controller 派生写入 —
	// 与训练/开发机同类 (非服务类)。缺此标志时写入层 (writer.go buildUpsert) 会跳过这两字段,
	// 导致前端"运行时长"永远算不出 (退化成 now-created_at)。
	//
	// 空值语义: startTime/endTime 未就绪时为空串 → writer 不写该字段 (保持缺失, 非 NULL),
	// 待 KubeRay 填值后 dedup 捕获 缺失→值 变化补写。缺失而非 NULL 是刻意为之: 让 MarkDeleted
	// 的 if_not_exists(ended_at, now) 能区分"从未结束"与"已有真实结束时刻"(见 writer.go)。
	// RayJob ttl_seconds_after_finished 默认 3600s, 终态到 CR 被 GC 之间有充足 reconcile 窗口
	// 读到 status.endTime; 用户中途停止 (删 CR, KubeRay 从没写 endTime) 则由 MarkDeleted 补
	// 停止时刻, 否则前端运行时长会在 stop 后继续往上涨。
	s := Status{
		Phase:                phase,
		OwnsLifecycleTimes:   true,
		StartedAt:            crSpecString(cr, "status", "startTime"),
		EndedAt:              crSpecString(cr, "status", "endTime"),
		LastConditionMessage: crSpecString(cr, "status", "message"),
		PriorityClass:        crLabel(cr, labelPriorityClass),
		StatusDetail:         statusDetail(cr),
	}

	ksRaw := deriveKueueFromWorkload(in.Workload)

	if ksRaw == "" {
		// 查不到 Workload: CR 终态 → Finished + Remove; 非终态 → 冻结。
		if terminal {
			s.KueueStatus = KueueFinished
			s.ActiveWS = rayOccupyingActive(in)
		} else {
			s.KueueStatus = "" // 冻结 (保持旧值)
			s.ActiveWS = ActiveFreeze
		}
		return s
	}

	if ksRaw != KueueFinished {
		// 非终态 (五态之一) → 活跃。
		s.KueueStatus = ksRaw
		s.ActiveWS = ActiveSet
		return s
	}

	// Workload Finished: 业务终态, 但 pod 可能仍在 ttl 窗口占卡 → 据 RayCluster 判 occupying。
	s.KueueStatus = KueueFinished
	s.ActiveWS = rayOccupyingActive(in)
	return s
}

// rayOccupyingActive: Ray 终态后据 RayCluster 是否仍存在判 active_ws。
// RayCluster 在 = head+worker Pod 仍在 ttl 窗口占 GPU → ActiveSet (occupying, 留在运行中);
// RayCluster 已删 (ttl 到期 shutdown, 级联删 Pod) = 资源真正释放 → ActiveRemove。
func rayOccupyingActive(in Inputs) ActiveDecision {
	if in.RayCluster != nil {
		return ActiveSet
	}
	return ActiveRemove
}
