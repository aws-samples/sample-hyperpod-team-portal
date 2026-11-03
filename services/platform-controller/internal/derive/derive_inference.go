package derive

import (
	"strings"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// 推理 (InferenceEndpointConfig CR) 派生。
//
// 与训练/开发机的关键差异 (会话 + 真集群实测确认):
//   - phase = status.deploymentStatus.deploymentObjectOverallState, 回退 status.state。
//     实测 state 会滞后卡在 DeploymentInProgress, overall 更贴近真实, 故 overall 优先。
//   - 关联 Workload = 2 跳 (查 Pod app=<CR名> → 最新 Pod uid → Workload), 在 reconciler。
//     实测推理 Workload 只有 QuotaReserved + Admitted 两个 condition, 永不自行 Finished;
//     排队等资源 = QuotaReserved=False (→ 六态 Queued)。
//   - 终态判定分两类 (已确定):
//       * 删除类 (Deletion* / Deleted): 前置短路, 直接 Finished, 不查 Workload
//         (真删除不可恢复, 无需看 Workload)。
//       * DeploymentFailed + 其它: 查 Workload — Workload 在则用六态 (可能还在排队/运行,
//         DeploymentFailed 可能只是临时失败, 资源来了能恢复, 不武断 Finished);
//         Workload 查不到才按 phase∈终态集判 Finished, 否则冻结 (还没建好)。
//   - endpoint_url: operator 只给 endpoints.sagemaker.endpointArn, 从 ARN 拼 runtime URL;
//     兼容旧字段 status.endpointUrl / invocationUrl。
//   - status_detail = {state, conditions, deploymentStatus} 三段 (与 Python 一致)。
//     实测稳态下 CR 不被写、时间戳不变, dedup 天然生效, 故照存完整片段无抖动风险。
//   - started_at / ended_at 留空 (推理无对应 condition 时间语义)。
//   - 单副本: 当前推理均单副本, workloadVia2Hop 的 pickLatestPod 取那唯一 Pod。
//     TODO(多副本): 将来多副本需改"取最好状态"而非"最近变化"。

// 推理删除类终态 (前置短路, 不查 Workload; 真删除不可恢复)。
var infDeletionStates = map[string]bool{
	"DeletionPending":    true,
	"DeletionInProgress": true,
	"DeletionFailed":     true,
	"DeletionComplete":   true,
	"Deleted":            true,
}

// 推理 "Workload 查不到时" 判 Finished 的终态集 = 删除类 + DeploymentFailed。
// (注意 Stopped 不在此: 那是平台状态, CR 无此 phase, 会话确认删除。)
func infPhaseIsFinished(phase string) bool {
	return infDeletionStates[phase] || phase == "DeploymentFailed"
}

func deriveInference(in Inputs) Status {
	cr := in.CR
	conds := crConditions(cr)
	phase := inferencePhase(cr)

	s := Status{
		Phase:                phase,
		LastConditionMessage: lastMessage(conds),
		PriorityClass:        crLabel(cr, labelPriorityClass),
		EndpointURL:          inferenceEndpointURL(cr),
		StatusDetail:         inferenceStatusDetail(cr),
		// started_at / ended_at 留空。
	}

	// 删除类终态: 前置短路 (不查 Workload, 真删除不可恢复)。
	if infDeletionStates[phase] {
		s.KueueStatus = KueueFinished
		s.ActiveWS = ActiveRemove
		return s
	}

	// 其它 (含 DeploymentFailed): 优先信 Workload。
	// 多副本聚合取【最好】(冗余关系, OR 语义): 一个副本好 = 服务可用, 其余排队只是容量
	// 降级 — 修掉旧 pickLatestPod 单 Workload 的时序巧合 (谁最近变化听谁的会随机摆动)。
	// 单副本时聚合退化为单 Workload 派生, 行为不变。
	ksRaw := aggregateKueueBest(in.Workloads)
	if ksRaw == "" {
		// Workload 查不到 (真没了 / 还没建):
		//   phase∈终态集 (DeploymentFailed) → 真失败, Finished + Remove;
		//   否则 (还没建好) → 冻结, 保持 DDB 旧值。
		if infPhaseIsFinished(phase) {
			s.KueueStatus = KueueFinished
			s.ActiveWS = ActiveRemove
		} else {
			s.KueueStatus = ""
			s.ActiveWS = ActiveFreeze
		}
		return s
	}

	// Workload 在: 用六态 (排队 Queued / 运行 Admitted; DeploymentFailed 时若 Workload
	// 仍活着说明还能恢复, 信 Workload 不武断 Finished)。
	s.KueueStatus = ksRaw
	if IsActive(ksRaw) {
		s.ActiveWS = ActiveSet
	} else {
		s.ActiveWS = ActiveRemove
	}
	return s
}

// inferencePhase: deploymentObjectOverallState 优先, 回退 status.state。
func inferencePhase(cr *unstructured.Unstructured) string {
	if v, found, _ := unstructured.NestedString(cr.Object,
		"status", "deploymentStatus", "deploymentObjectOverallState"); found && v != "" {
		return v
	}
	v, _, _ := unstructured.NestedString(cr.Object, "status", "state")
	return v
}

// inferenceEndpointURL: operator 不填 status.endpointUrl, 只给 endpoints.sagemaker.endpointArn;
// 从 ARN 拼 SageMaker runtime URL。兼容旧字段 endpointUrl / invocationUrl。
func inferenceEndpointURL(cr *unstructured.Unstructured) string {
	if v, _, _ := unstructured.NestedString(cr.Object, "status", "endpointUrl"); v != "" {
		return v
	}
	if v, _, _ := unstructured.NestedString(cr.Object, "status", "invocationUrl"); v != "" {
		return v
	}
	arn, _, _ := unstructured.NestedString(cr.Object,
		"status", "endpoints", "sagemaker", "endpointArn")
	return runtimeURLFromARN(arn)
}

// runtimeURLFromARN: SageMaker endpoint ARN → runtime invoke URL (对应 Python runtime_url_from_arn)。
//   ARN: arn:aws:sagemaker:<region>:<acct>:endpoint/<name>
//   URL: https://runtime.sagemaker.<region>.amazonaws.com/endpoints/<name>/invocations
func runtimeURLFromARN(arn string) string {
	if arn == "" {
		return ""
	}
	parts := strings.Split(arn, ":")
	if len(parts) < 6 || !strings.Contains(parts[5], "/") {
		return ""
	}
	region := parts[3]
	name := strings.SplitN(parts[5], "/", 2)[1]
	if region == "" || name == "" {
		return ""
	}
	return "https://runtime.sagemaker." + region + ".amazonaws.com/endpoints/" + name + "/invocations"
}

// inferenceStatusDetail: {state, conditions, deploymentStatus} 三段 (与 Python 一致)。
func inferenceStatusDetail(cr *unstructured.Unstructured) map[string]any {
	state, _, _ := unstructured.NestedString(cr.Object, "status", "state")
	conditions, _, _ := unstructured.NestedSlice(cr.Object, "status", "conditions")
	deployStatus, _, _ := unstructured.NestedMap(cr.Object, "status", "deploymentStatus")
	return map[string]any{
		"state":            state,
		"conditions":       conditions,
		"deploymentStatus": deployStatus,
	}
}
