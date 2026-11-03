package derive

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// mkInferenceCR 造一个指定 phase 的推理 CR (测试夹具)。
func mkInferenceCR(state string) *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "inference.sagemaker.aws.amazon.com/v1",
		"kind":       "InferenceEndpointConfig",
		"metadata":   map[string]any{"name": "inf1"},
		"status":     map[string]any{"state": state},
	}}
}

// 推理多副本: kueue_status 从全部 Workload 聚合取最好 (冗余关系, 一个副本好=服务可用),
// 修 pickLatestPod 单 Workload 的时序巧合 bug (谁最近变化听谁的)。
func TestDeriveInferenceMultiReplica(t *testing.T) {
	t.Run("Admitted+Queued→取最好Admitted+Set", func(t *testing.T) {
		s := deriveInference(Inputs{
			CR: mkInferenceCR("DeploymentInProgress"),
			Workloads: []*unstructured.Unstructured{
				mkWorkload(), // 副本 B: 排队 (无 True condition → Queued)
				mkWorkload(KueueQuotaReserved, KueueAdmitted), // 副本 A: 已准入
			},
		})
		if s.KueueStatus != KueueAdmitted {
			t.Errorf("KueueStatus = %q, want %q", s.KueueStatus, KueueAdmitted)
		}
		if s.ActiveWS != ActiveSet {
			t.Errorf("ActiveWS = %v, want ActiveSet", s.ActiveWS)
		}
	})

	t.Run("单副本行为不变: 单Workload Admitted", func(t *testing.T) {
		s := deriveInference(Inputs{
			CR:        mkInferenceCR("DeploymentComplete"),
			Workloads: []*unstructured.Unstructured{mkWorkload(KueueQuotaReserved, KueueAdmitted)},
		})
		if s.KueueStatus != KueueAdmitted {
			t.Errorf("KueueStatus = %q, want %q", s.KueueStatus, KueueAdmitted)
		}
	})

	t.Run("Workload空集+非终态phase→冻结", func(t *testing.T) {
		s := deriveInference(Inputs{CR: mkInferenceCR("DeploymentInProgress")})
		if s.KueueStatus != "" {
			t.Errorf("KueueStatus = %q, want 空串(冻结)", s.KueueStatus)
		}
		if s.ActiveWS != ActiveFreeze {
			t.Errorf("ActiveWS = %v, want ActiveFreeze", s.ActiveWS)
		}
	})

	t.Run("Workload空集+DeploymentFailed→Finished+Remove", func(t *testing.T) {
		s := deriveInference(Inputs{CR: mkInferenceCR("DeploymentFailed")})
		if s.KueueStatus != KueueFinished {
			t.Errorf("KueueStatus = %q, want %q", s.KueueStatus, KueueFinished)
		}
		if s.ActiveWS != ActiveRemove {
			t.Errorf("ActiveWS = %v, want ActiveRemove", s.ActiveWS)
		}
	})

	t.Run("删除类终态前置短路: 有Workload也Finished", func(t *testing.T) {
		s := deriveInference(Inputs{
			CR:        mkInferenceCR("DeletionInProgress"),
			Workloads: []*unstructured.Unstructured{mkWorkload(KueueAdmitted)},
		})
		if s.KueueStatus != KueueFinished {
			t.Errorf("KueueStatus = %q, want %q", s.KueueStatus, KueueFinished)
		}
	})
}
