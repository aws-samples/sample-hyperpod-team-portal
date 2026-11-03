package derive

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// mkRayCRFull 造一个带指定 jobStatus + jobDeploymentStatus 的 RayJob CR。
func mkRayCRFull(jobStatus, deployStatus string) *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "ray.io/v1",
		"kind":       "RayJob",
		"metadata":   map[string]any{"name": "ray-x", "namespace": "ns1"},
		"status": map[string]any{
			"jobStatus":           jobStatus,
			"jobDeploymentStatus": deployStatus,
		},
	}}
}

// mkRayCluster 造一个最简 RayCluster (仅用于表示"存在", 派生只判 nil/非 nil)。
func mkRayCluster() *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "ray.io/v1",
		"kind":       "RayCluster",
		"metadata":   map[string]any{"name": "ray-x-abc12", "namespace": "ns1"},
	}}
}

// TestDeriveRayLifecycleTimes 验证 RayJob 从 CR status.startTime/endTime 派生 started_at/ended_at,
// 并把 OwnsLifecycleTimes 置 true (否则 writer 会跳过这两字段, 前端运行时长算不出)。
func TestDeriveRayLifecycleTimes(t *testing.T) {
	cr := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "ray.io/v1",
		"kind":       "RayJob",
		"metadata":   map[string]any{"name": "ray-x", "namespace": "ns1"},
		"status": map[string]any{
			"jobStatus": "SUCCEEDED",
			"startTime": "2026-08-27T10:00:00Z",
			"endTime":   "2026-08-27T10:30:00Z",
		},
	}}
	got := deriveRay(Inputs{CR: cr, Workload: nil})
	if !got.OwnsLifecycleTimes {
		t.Errorf("OwnsLifecycleTimes = false, want true")
	}
	if got.StartedAt != "2026-08-27T10:00:00Z" {
		t.Errorf("StartedAt = %q, want status.startTime", got.StartedAt)
	}
	if got.EndedAt != "2026-08-27T10:30:00Z" {
		t.Errorf("EndedAt = %q, want status.endTime", got.EndedAt)
	}

	// 未就绪 (无 startTime/endTime): 两字段空串 (writer 写 NULL), OwnsLifecycleTimes 仍为 true。
	running := deriveRay(Inputs{CR: mkRayCRFull("RUNNING", ""), Workload: mkWorkload(KueuePodsReady)})
	if !running.OwnsLifecycleTimes {
		t.Errorf("running OwnsLifecycleTimes = false, want true")
	}
	if running.StartedAt != "" || running.EndedAt != "" {
		t.Errorf("running StartedAt/EndedAt = %q/%q, want empty", running.StartedAt, running.EndedAt)
	}
}

func TestDeriveRay(t *testing.T) {
	cases := []struct {
		name         string
		jobStatus    string
		deployStatus string
		workload     *unstructured.Unstructured
		rayCluster   *unstructured.Unstructured
		wantPhase    string
		wantKS       string
		wantActive   ActiveDecision
	}{
		{
			name:      "运行中: Workload PodsReady → 活跃",
			jobStatus: "RUNNING", workload: mkWorkload(KueueQuotaReserved, KueueAdmitted, KueuePodsReady),
			wantPhase: "RUNNING", wantKS: KueuePodsReady, wantActive: ActiveSet,
		},
		{
			name:      "排队中: Workload 无 True condition → Queued 活跃",
			jobStatus: "PENDING", workload: mkWorkload(),
			wantPhase: "PENDING", wantKS: KueueQueued, wantActive: ActiveSet,
		},
		{
			name:      "成功: Workload Finished → Remove",
			jobStatus: "SUCCEEDED", workload: mkWorkload(KueueAdmitted, KueuePodsReady, KueueFinished),
			wantPhase: "SUCCEEDED", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "终态占卡窗口: Workload Finished 但 RayCluster 仍在 → occupying 保持活跃",
			jobStatus: "SUCCEEDED", workload: mkWorkload(KueueAdmitted, KueuePodsReady, KueueFinished),
			rayCluster: mkRayCluster(),
			wantPhase:  "SUCCEEDED", wantKS: KueueFinished, wantActive: ActiveSet,
		},
		{
			name:      "终态资源已释放: Workload Finished 且 RayCluster 已删 → Remove",
			jobStatus: "SUCCEEDED", workload: mkWorkload(KueueAdmitted, KueuePodsReady, KueueFinished),
			rayCluster: nil,
			wantPhase:  "SUCCEEDED", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "成功但 Workload 已删: CR 终态 → Finished + Remove",
			jobStatus: "SUCCEEDED", workload: nil,
			wantPhase: "SUCCEEDED", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "失败但 Workload 已删: CR 终态 → Finished + Remove",
			jobStatus: "FAILED", workload: nil,
			wantPhase: "FAILED", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "非终态但 Workload 查不到: 冻结 (保持旧值)",
			jobStatus: "RUNNING", workload: nil,
			wantPhase: "RUNNING", wantKS: "", wantActive: ActiveFreeze,
		},
		{
			name:      "STOPPED 也是终态 → Remove",
			jobStatus: "STOPPED", workload: nil,
			wantPhase: "STOPPED", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "jobStatus 空 + deployStatus=Suspended: 回退标注 → 冻结",
			jobStatus: "", deployStatus: "Suspended", workload: nil,
			wantPhase: "Suspended (Deploy Status)", wantKS: "", wantActive: ActiveFreeze,
		},
		{
			name:      "jobStatus 空 + deployStatus=Initializing: 回退标注 → 冻结",
			jobStatus: "", deployStatus: "Initializing", workload: nil,
			wantPhase: "Initializing (Deploy Status)", wantKS: "", wantActive: ActiveFreeze,
		},
		{
			name:      "编排失败: jobStatus 空 + deployStatus=Failed → 终态 Finished + Remove",
			jobStatus: "", deployStatus: "Failed", workload: nil,
			wantPhase: "Failed (Deploy Status)", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "jobStatus 空 + deployStatus=Complete → 终态 Finished + Remove",
			jobStatus: "", deployStatus: "Complete", workload: nil,
			wantPhase: "Complete (Deploy Status)", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
		{
			name:      "两维度都空 → phase 空, 非终态 → 冻结",
			jobStatus: "", deployStatus: "", workload: nil,
			wantPhase: "", wantKS: "", wantActive: ActiveFreeze,
		},
		{
			name:      "jobStatus 非空压制 deployStatus: SUCCEEDED 胜出 (无视 deployStatus=Running) → 终态 Remove",
			jobStatus: "SUCCEEDED", deployStatus: "Running", workload: nil,
			wantPhase: "SUCCEEDED", wantKS: KueueFinished, wantActive: ActiveRemove,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := deriveRay(Inputs{CR: mkRayCRFull(tc.jobStatus, tc.deployStatus), Workload: tc.workload, RayCluster: tc.rayCluster})
			if got.Phase != tc.wantPhase {
				t.Errorf("Phase = %q, want %q", got.Phase, tc.wantPhase)
			}
			if got.KueueStatus != tc.wantKS {
				t.Errorf("KueueStatus = %q, want %q", got.KueueStatus, tc.wantKS)
			}
			if got.ActiveWS != tc.wantActive {
				t.Errorf("ActiveWS = %v, want %v", got.ActiveWS, tc.wantActive)
			}
		})
	}
}
