package derive

import (
	"context"
	"sort"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// 训练 CR Pod 上标识所属 CR 的 label (单一真相源在 gvk 包; 与 cache 的 !HPJob 排除一致)。
const trainPodLabelKey = gvk.LabelTrainingPodCRName

// 训练 priority-class label。
const labelPriorityClass = "kueue.x-k8s.io/priority-class"

// CR phase 优先级 (时间戳相同打破平局, 从高到低)。对应 worker/phase.py 的 _CR_PHASE_PRIORITY
// 训练相关部分 (终态 > 运行 > 进行中)。
var trainPhasePriority = []string{
	"Failed", "Complete", "Completed", "Succeeded", // 终态
	"Running", "Started", "PodsRunning", "Faulted", // 运行
	"Created", "Suspended", // 创建/挂起
}

// deriveTraining 实现训练的完整派生 (决策表见会话讨论)。
func deriveTraining(ctx context.Context, in Inputs) Status {
	cr := in.CR
	conds := crConditions(cr)
	trues := trueConds(conds)

	s := Status{
		Phase:                pickSinglePhase(trues, trainPhasePriority),
		OwnsLifecycleTimes:   true, // 训练有终态 condition, started/ended 由 controller 派生
		StartedAt:            phaseTime(conds, "Running", "Created"),
		EndedAt:              terminalTime(conds, "Complete", "Failed"),
		LastConditionMessage: lastMessage(conds),
		PriorityClass:        crLabel(cr, labelPriorityClass),
		StatusDetail:         statusDetail(cr),
	}

	// ── kueue_status + active_ws 决策 ──
	ksRaw := deriveKueueFromWorkload(in.Workload)

	if ksRaw == "" {
		// 查不到 Workload: CR 终态 → Finished 短路; 非终态 → 冻结 (保持旧值)。
		if crIsTrainTerminal(conds) {
			s.KueueStatus = KueueFinished
			s.ActiveWS = trainOccupyingActive(ctx, in, conds) // 终态仍要按 occupying 决定 active_ws
		} else {
			s.KueueStatus = "" // 冻结
			s.ActiveWS = ActiveFreeze
		}
		return s
	}

	if ksRaw != KueueFinished {
		// 非终态六态 → 活跃。
		s.KueueStatus = ksRaw
		s.ActiveWS = ActiveSet
		return s
	}

	// ksRaw == Finished: 按 CR 状态 + cleanPodPolicy 决定 active_ws (occupying 决策表)。
	s.KueueStatus = KueueFinished
	s.ActiveWS = trainOccupyingActive(ctx, in, conds)
	return s
}

// trainOccupyingActive 实现训练 Finished 后的 active_ws 决策表 (会话确认版):
//
//	cleanPodPolicy == None:        查 Pod (不看 CR 状态) → 有存活 Pod? Set : Remove
//	cleanPodPolicy == All / 空:     不查 → Remove (Pod 注定被清)
//	cleanPodPolicy == OnlyComplete: CR Completed → Remove; CR Failed → 查 Pod; CR 中间态 → Freeze
//	未知 policy:                     保守 Remove
func trainOccupyingActive(ctx context.Context, in Inputs, conds []cond) ActiveDecision {
	policy := crSpecString(in.CR, "spec", "runPolicy", "cleanPodPolicy")
	switch policy {
	case "None":
		return activeByLivePod(ctx, in)
	case "All", "":
		return ActiveRemove
	case "OnlyComplete":
		if hasTrueTypeContaining(conds, "Complete") {
			return ActiveRemove // 成功 Pod 会被清
		}
		if hasTrueTypeContaining(conds, "Failed") {
			return activeByLivePod(ctx, in) // 失败 Pod 残留
		}
		return ActiveFreeze // 中间态: CR 既非 Completed 也非 Failed, 等稳态
	default:
		return ActiveRemove
	}
}

// activeByLivePod 查该训练 CR 的 Pod, 有 Running/Pending → Set (占卡), 否则 Remove。
// 查询失败 → 保守 Remove (不阻塞; 与 Python 现查不到不占卡一致)。
func activeByLivePod(ctx context.Context, in Inputs) ActiveDecision {
	if in.Pods == nil {
		return ActiveRemove
	}
	name := in.CR.GetName()
	ns := in.CR.GetNamespace()
	if name == "" || ns == "" {
		return ActiveRemove
	}
	pods, err := in.Pods(ctx, ns, trainPodLabelKey+"="+name)
	if err != nil {
		return ActiveRemove
	}
	for _, p := range pods {
		phase, _, _ := unstructuredString(p, "status", "phase")
		if phase == "Running" || phase == "Pending" {
			return ActiveSet
		}
	}
	return ActiveRemove
}

// crIsTrainTerminal: 训练 CR 是否终态 (conditions 有 status==True 且 type 含 Complete/Failed)。
func crIsTrainTerminal(conds []cond) bool {
	return hasTrueTypeContaining(conds, "Complete") || hasTrueTypeContaining(conds, "Failed")
}

// ── phase 派生辅助 (对应 worker/phase.py) ──

// pickSinglePhase: 从 status==True 的 conditions 取单个 — 先 lastTransitionTime 最新,
// 时间戳相同按 priority (rank 小在前)。无 True → ""。
func pickSinglePhase(trues []cond, priority []string) string {
	if len(trues) == 0 {
		return ""
	}
	rank := func(t string) int {
		for i, p := range priority {
			if p == t {
				return i
			}
		}
		return len(priority)
	}
	sort.SliceStable(trues, func(i, j int) bool {
		// lastTransitionTime 降序 (新在前); 相同则 rank 升序 (优先级高在前)
		if trues[i].LastTransitionTime != trues[j].LastTransitionTime {
			return trues[i].LastTransitionTime > trues[j].LastTransitionTime
		}
		return rank(trues[i].Type) < rank(trues[j].Type)
	})
	return trues[0].Type
}

// phaseTime: 取首个匹配 type 的 lastTransitionTime (按给定顺序优先)。
func phaseTime(conds []cond, types ...string) string {
	byType := map[string]string{}
	for _, c := range conds {
		if _, ok := byType[c.Type]; !ok {
			byType[c.Type] = c.LastTransitionTime
		}
	}
	for _, t := range types {
		if v := byType[t]; v != "" {
			return v
		}
	}
	return ""
}

// terminalTime: 取 status==True 且 type 含任一 substr 的最新 lastTransitionTime。
func terminalTime(conds []cond, substrs ...string) string {
	best := ""
	for _, c := range conds {
		if c.Status != "True" {
			continue
		}
		match := false
		for _, sub := range substrs {
			if containsStr(c.Type, sub) {
				match = true
				break
			}
		}
		if match && c.LastTransitionTime > best {
			best = c.LastTransitionTime
		}
	}
	return best
}

// lastMessage: 最后一条 condition 的 message。
func lastMessage(conds []cond) string {
	if len(conds) == 0 {
		return ""
	}
	return conds[len(conds)-1].Message
}
