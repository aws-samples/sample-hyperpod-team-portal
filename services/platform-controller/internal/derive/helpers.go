package derive

import (
	"strings"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// statusDetail 取 CR 的整个 status (训练: 原样作 debug 弹窗用)。
func statusDetail(obj *unstructured.Unstructured) map[string]any {
	if obj == nil {
		return map[string]any{}
	}
	st, found, _ := unstructured.NestedMap(obj.Object, "status")
	if !found || st == nil {
		return map[string]any{}
	}
	return st
}

// unstructuredString 取嵌套字符串字段。
func unstructuredString(obj *unstructured.Unstructured, path ...string) (string, bool, error) {
	if obj == nil {
		return "", false, nil
	}
	return unstructured.NestedString(obj.Object, path...)
}

func containsStr(s, sub string) bool { return strings.Contains(s, sub) }
