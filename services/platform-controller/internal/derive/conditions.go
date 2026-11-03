package derive

import (
	"strings"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// cond 是从 unstructured status.conditions 取出的一条 (只保留我们用到的字段)。
type cond struct {
	Type               string
	Status             string
	Message            string
	LastTransitionTime string
}

// crConditions 取 CR/Workload 的 status.conditions, 转成 []cond。
func crConditions(obj *unstructured.Unstructured) []cond {
	if obj == nil {
		return nil
	}
	raw, _, _ := unstructured.NestedSlice(obj.Object, "status", "conditions")
	out := make([]cond, 0, len(raw))
	for _, c := range raw {
		m, ok := c.(map[string]any)
		if !ok {
			continue
		}
		t, _ := m["type"].(string)
		s, _ := m["status"].(string)
		msg, _ := m["message"].(string)
		lt, _ := m["lastTransitionTime"].(string)
		out = append(out, cond{Type: t, Status: s, Message: msg, LastTransitionTime: lt})
	}
	return out
}

// trueConds 过滤出 status==True 的 condition。
func trueConds(conds []cond) []cond {
	var out []cond
	for _, c := range conds {
		if c.Status == "True" && c.Type != "" {
			out = append(out, c)
		}
	}
	return out
}

// crLabel 取 CR 的某个 metadata.label。
func crLabel(obj *unstructured.Unstructured, key string) string {
	if obj == nil {
		return ""
	}
	return obj.GetLabels()[key]
}

// crSpecString 取 CR spec 下的嵌套字符串字段 (如 spec.runPolicy.cleanPodPolicy)。
func crSpecString(obj *unstructured.Unstructured, path ...string) string {
	if obj == nil {
		return ""
	}
	v, _, _ := unstructured.NestedString(obj.Object, path...)
	return v
}

// hasTrueTypeContaining: conditions 里有没有 status==True 且 type 含 substr 的 (子串匹配)。
// 用于 CR 终态判定 — operator 终态 type 名不统一 (Complete vs Completed), 子串覆盖。
func hasTrueTypeContaining(conds []cond, substr string) bool {
	for _, c := range conds {
		if c.Status == "True" && strings.Contains(c.Type, substr) {
			return true
		}
	}
	return false
}
