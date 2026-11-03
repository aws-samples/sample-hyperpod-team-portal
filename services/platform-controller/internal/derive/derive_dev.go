package derive

// 开发机 (Workspace CR) 派生。
//
// 与训练的关键差异 (会话确认):
//   - 终态短路: 仅 phase 含 "Stopped" → Finished (Stopped=资源已 scaled down)。
//     Degraded 不短路 (CRD: Degraded=未达/未维持期望态, 是故障非终态, 可能还占资源) —
//     走查 Workload, 占资源则留活跃列表 (故障可见)。
//   - 无 occupying (Stopped 时 Pod 已释放, 不存在占卡)。active_ws = is_active(ks)。
//   - started_at = Available condition; ended_at = Stopped condition。
//   - status_detail = 所有 status==True 的 condition 数组 (非整个 status)。
//   - 关联 Workload = 2 跳 (查 Pod → Pod uid → Workload), 在 reconciler.fetchWorkload。
//   - ks 查不到 Workload → 冻结 (保持旧值); 重启 (Stopped→Running) 靠 phase 变化 +
//     新 Workload 事件自然恢复, 无需特殊代码。

// 开发机 CR phase 优先级 (时间戳相同打破平局): 终态 > 故障 > 运行 > 进行中。
var devPhasePriority = []string{
	"Stopped", "Degraded", // 终态 / 故障 (Stopped 优先级最高)
	"Available",                  // 运行就绪
	"Progressing", "Initialized", // 进行中
}

func deriveDev(in Inputs) Status {
	cr := in.CR
	conds := crConditions(cr)
	trues := trueConds(conds)

	s := Status{
		Phase:                pickSinglePhase(trues, devPhasePriority),
		OwnsLifecycleTimes:   true, // 开发机有 Available/Stopped condition, started/ended 由 controller 派生
		StartedAt:            phaseTime(conds, "Available"),
		EndedAt:              phaseTime(conds, "Stopped"),
		LastConditionMessage: lastMessage(conds),
		PriorityClass:        crLabel(cr, labelPriorityClass),
		StatusDetail:         trueCondsDetail(trues), // status==True 的 condition 数组
	}

	phase := s.Phase

	// 终态短路: 仅 Stopped (资源已释放, 不查 Workload; 避开停止瞬间 Workload 删除竞态)。
	if containsStr(phase, "Stopped") {
		s.KueueStatus = KueueFinished
		s.ActiveWS = ActiveRemove
		return s
	}

	// 非 Stopped (含 Degraded/Available/Progressing): 查 Workload 镜像六态。
	ksRaw := deriveKueueFromWorkload(in.Workload)
	if ksRaw == "" {
		// 查不到 Workload (还没建 / 已删): 冻结, 保持 DDB 旧值。
		s.KueueStatus = ""
		s.ActiveWS = ActiveFreeze
		return s
	}
	s.KueueStatus = ksRaw
	if IsActive(ksRaw) {
		s.ActiveWS = ActiveSet
	} else {
		s.ActiveWS = ActiveRemove // Finished (但开发机非终态时 Workload 一般不会 Finished)
	}
	return s
}

// trueCondsDetail 把 status==True 的 condition 转成 []any (供 status_detail 写 DDB)。
// 结构与 Python 开发机 informer 的 true_conds 一致 (原始 condition 字段)。
func trueCondsDetail(trues []cond) []any {
	out := make([]any, 0, len(trues))
	for _, c := range trues {
		out = append(out, map[string]any{
			"type":               c.Type,
			"status":             c.Status,
			"message":            c.Message,
			"lastTransitionTime": c.LastTransitionTime,
		})
	}
	return out
}
