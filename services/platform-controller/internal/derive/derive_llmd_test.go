package derive

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// mkLWS 造一个带指定 conditions 的 LWS (status 数值字段固定 2/4, 模拟部分准入)。
func mkLWS(trueCondType string) *unstructured.Unstructured {
	conds := []any{}
	if trueCondType != "" {
		conds = append(conds, map[string]any{"type": trueCondType, "status": "True"})
	}
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "leaderworkerset.x-k8s.io/v1",
		"kind":       "LeaderWorkerSet",
		"metadata":   map[string]any{"name": "t1-multi"},
		"status": map[string]any{
			"conditions": conds, "replicas": int64(4), "readyReplicas": int64(2),
		},
	}}
}

// mkGwDeploy 造一个 gateway Deployment (Available=True 稳态; Progressing 恒 True 是 Deployment 特性)。
func mkGwDeploy() *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "apps/v1",
		"kind":       "Deployment",
		"metadata":   map[string]any{"name": "t1-gateway", "namespace": "ns1"},
		"status": map[string]any{
			"conditions": []any{
				map[string]any{"type": "Available", "status": "True"},
				map[string]any{"type": "Progressing", "status": "True"},
			},
			"replicas": int64(2), "readyReplicas": int64(2),
		},
	}}
}

// llmd 派生: phase=LWS condition 原样(仅 Stopped 自加); ks=LWS Workloads 取最好;
// gateway 四字段独立; active_ws 双 deleted 才 Remove。
func TestDeriveLlmd(t *testing.T) {
	t.Run("运行态: LWS Available + 部分准入 → 取最好 Admitted + Set", func(t *testing.T) {
		s := deriveLlmd(Inputs{
			LWS: mkLWS("Available"),
			Workloads: []*unstructured.Unstructured{
				mkWorkload(KueueQuotaReserved, KueueAdmitted),
				mkWorkload(),
			},
			GatewayDeploy:    mkGwDeploy(),
			GatewayWorkloads: []*unstructured.Unstructured{mkWorkload(KueueAdmitted)},
		})
		if s.Phase != "Available" {
			t.Errorf("Phase = %q, want Available (LWS condition 原样)", s.Phase)
		}
		if s.KueueStatus != KueueAdmitted {
			t.Errorf("KueueStatus = %q, want Admitted (聚合取最好)", s.KueueStatus)
		}
		if s.GatewayPhase != "Available" {
			t.Errorf("GatewayPhase = %q, want Available", s.GatewayPhase)
		}
		if s.GatewayKueueStatus != KueueAdmitted {
			t.Errorf("GatewayKueueStatus = %q, want Admitted", s.GatewayKueueStatus)
		}
		if s.ActiveWS != ActiveSet {
			t.Errorf("ActiveWS = %v, want Set", s.ActiveWS)
		}
		if s.LwsDeleted || s.GatewayDeleted {
			t.Error("运行态不应标 deleted")
		}
		if want := "http://t1-gateway.ns1.svc.cluster.local:30000"; s.EndpointURL != want {
			t.Errorf("EndpointURL = %q, want %q", s.EndpointURL, want)
		}
	})

	t.Run("LWS Progressing + Workload 空集 → 冻结", func(t *testing.T) {
		s := deriveLlmd(Inputs{LWS: mkLWS("Progressing"), GatewayDeploy: mkGwDeploy()})
		if s.Phase != "Progressing" {
			t.Errorf("Phase = %q, want Progressing", s.Phase)
		}
		if s.KueueStatus != "" {
			t.Errorf("KueueStatus = %q, want 空串冻结", s.KueueStatus)
		}
		if s.ActiveWS != ActiveFreeze {
			t.Errorf("ActiveWS = %v, want Freeze", s.ActiveWS)
		}
	})

	t.Run("刚创建 conditions 空 → phase 空串冻结", func(t *testing.T) {
		s := deriveLlmd(Inputs{LWS: mkLWS(""), GatewayDeploy: mkGwDeploy()})
		if s.Phase != "" {
			t.Errorf("Phase = %q, want 空串 (Available 可能整个缺席, 实证)", s.Phase)
		}
	})

	t.Run("半删态: LWS 删 gateway 在 → Stopped+Finished+LwsDeleted, active Freeze", func(t *testing.T) {
		s := deriveLlmd(Inputs{
			LWS: nil, GatewayDeploy: mkGwDeploy(),
			GatewayWorkloads: []*unstructured.Unstructured{mkWorkload(KueueAdmitted)},
		})
		if s.Phase != "Stopped" || s.KueueStatus != KueueFinished {
			t.Errorf("phase/ks = %q/%q, want Stopped/Finished", s.Phase, s.KueueStatus)
		}
		if !s.LwsDeleted {
			t.Error("LwsDeleted 应为 true")
		}
		if s.GatewayDeleted {
			t.Error("gateway 还在, GatewayDeleted 应为 false")
		}
		if s.ActiveWS != ActiveFreeze {
			t.Errorf("ActiveWS = %v, want Freeze (gateway 仍占配额, 泄漏显性化)", s.ActiveWS)
		}
	})

	t.Run("反向半删态: gateway 删 LWS 在 → GatewayDeleted+gateway ks Finished, 主状态照常", func(t *testing.T) {
		s := deriveLlmd(Inputs{
			LWS:       mkLWS("Available"),
			Workloads: []*unstructured.Unstructured{mkWorkload(KueueAdmitted)},
		})
		if !s.GatewayDeleted {
			t.Error("GatewayDeleted 应为 true")
		}
		if s.GatewayKueueStatus != KueueFinished {
			t.Errorf("GatewayKueueStatus = %q, want Finished", s.GatewayKueueStatus)
		}
		if s.KueueStatus != KueueAdmitted || s.ActiveWS != ActiveSet {
			t.Errorf("主状态不应受 gateway 影响: ks=%q active=%v", s.KueueStatus, s.ActiveWS)
		}
	})

	t.Run("双删 → Remove active_ws", func(t *testing.T) {
		s := deriveLlmd(Inputs{})
		if s.ActiveWS != ActiveRemove {
			t.Errorf("ActiveWS = %v, want Remove (双 deleted 齐)", s.ActiveWS)
		}
		if !s.LwsDeleted || !s.GatewayDeleted {
			t.Error("双 deleted 都应为 true")
		}
	})

	t.Run("Progressing+UpdateInProgress 并存 → 优先报 Progressing", func(t *testing.T) {
		lws := mkLWS("Progressing")
		conds, _, _ := unstructured.NestedSlice(lws.Object, "status", "conditions")
		conds = append(conds, map[string]any{"type": "UpdateInProgress", "status": "True"})
		_ = unstructured.SetNestedSlice(lws.Object, conds, "status", "conditions")
		s := deriveLlmd(Inputs{LWS: lws, GatewayDeploy: mkGwDeploy()})
		if s.Phase != "Progressing" {
			t.Errorf("Phase = %q, want Progressing (UpdateInProgress 不上位)", s.Phase)
		}
	})
}
