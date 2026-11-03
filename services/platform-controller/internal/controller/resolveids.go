package controller

import (
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// CR metadata.labels 上标识 DDB 主键的 key (实测确认, 三类共用 workspace-id;
// resource_id 各类不同 label key)。
const (
	labelWorkspaceID = "platform.hyperpod.io/workspace-id"
	labelTrainingJob = "platform.hyperpod.io/training-job-id"
	labelInferenceID = "platform.hyperpod.io/inference-id"
	labelDevInstance = "platform.hyperpod.io/dev-instance-id"
	labelDynamoID    = "platform.hyperpod.io/dynamo-id" // 实测确认: 平台创建的 DGD 带此 label
	labelRayjobID    = "platform.hyperpod.io/rayjob-id" // 实测确认: 平台创建的 RayJob 带此 label
)

// resolveIDsFor 返回某类 CR 的 (resourceID, workspaceID) 解析函数。
//
// 当前只实现 label 路径 (正常 UI 创建的 CR 都带这两个 label)。
// TODO: "绕过 UI / kubectl 提交"的兜底 (namespace 反推 ws + uid/name 作 id) 未实现 —
//
//	那依赖 workspace 查询, Go controller 暂无; 缺 label 的 CR 会被跳过 (返回 ok=false)。
func resolveIDsFor(crKind string) func(*unstructured.Unstructured) (string, string, bool) {
	idLabel := resourceIDLabelFor(crKind)
	return func(cr *unstructured.Unstructured) (string, string, bool) {
		labels := cr.GetLabels()
		rid := labels[idLabel]
		ws := labels[labelWorkspaceID]
		if rid == "" || ws == "" {
			return "", "", false
		}
		return rid, ws, true
	}
}

func resourceIDLabelFor(crKind string) string {
	switch crKind {
	case gvk.Training.Kind:
		return labelTrainingJob
	case gvk.Inference.Kind:
		return labelInferenceID
	case gvk.DevInstance.Kind:
		return labelDevInstance
	case gvk.DynamoGraph.Kind:
		return labelDynamoID
	case gvk.RayJob.Kind:
		return labelRayjobID
	default:
		return ""
	}
}
