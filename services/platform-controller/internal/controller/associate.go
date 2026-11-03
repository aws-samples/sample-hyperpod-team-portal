package controller

import (
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// 开发机/推理 Pod 上标识所属 CR name 的 label key (实测确认)。
const (
	devPodLabelKey = "workspace.jupyter.org/workspace-name" // 开发机 Pod: =<CR name>
	infPodLabelKey = "app"                                  // 推理 Pod: =<CR name>
)

// pickLatestPod 多 Pod 取"最近状态变化"的 (status.conditions 最大 lastTransitionTime)。
// 对应 Python pick_latest_pod: 多副本下选最能反映当前状态的; 单副本时就那一个。
// 无 conditions 回退 metadata.creationTimestamp。
func pickLatestPod(pods []*unstructured.Unstructured) *unstructured.Unstructured {
	var best *unstructured.Unstructured
	var bestTS string
	for _, p := range pods {
		ts := latestTransitionTime(p)
		if best == nil || ts > bestTS {
			best, bestTS = p, ts
		}
	}
	return best
}

// latestTransitionTime: status.conditions 里最大的 lastTransitionTime;
// 无则回退 metadata.creationTimestamp。ISO8601 字典序 == 时间序。
func latestTransitionTime(obj *unstructured.Unstructured) string {
	conds, _, _ := unstructured.NestedSlice(obj.Object, "status", "conditions")
	best := ""
	for _, c := range conds {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		if t, _ := m["lastTransitionTime"].(string); t > best {
			best = t
		}
	}
	if best != "" {
		return best
	}
	ct, _, _ := unstructured.NestedString(obj.Object, "metadata", "creationTimestamp")
	return ct
}
