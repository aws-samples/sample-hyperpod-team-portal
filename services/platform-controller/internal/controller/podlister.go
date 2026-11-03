package controller

import (
	"context"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/derive"
)

// newPodLister 构造 derive.PodLister: 按 label 查 Pod。
//
// 专用于训练 occupying: 训练 Pod (HPJob label) 被 !HPJob selector 挡在 cache 外
// (上百且抖动, 见 main.go), 故只能用 apiReader (mgr.GetAPIReader, 直连 API) 直查。
// occupying 是窄场景 (失败训练), 查询频率低, 直查可接受。
// (推理/开发机的 2 跳查 Pod 走 cache, 见 reconciler.workloadVia2Hop, 不经这里。)
func newPodLister(apiReader client.Reader) derive.PodLister {
	return func(ctx context.Context, namespace, labelSelector string) ([]*unstructured.Unstructured, error) {
		var podList corev1.PodList
		sel, err := labelsFromSelector(labelSelector)
		if err != nil {
			return nil, err
		}
		if err := apiReader.List(ctx, &podList,
			client.InNamespace(namespace),
			client.MatchingLabels(sel),
		); err != nil {
			return nil, err
		}
		out := make([]*unstructured.Unstructured, 0, len(podList.Items))
		for i := range podList.Items {
			m, err := runtime.DefaultUnstructuredConverter.ToUnstructured(&podList.Items[i])
			if err != nil {
				continue
			}
			out = append(out, &unstructured.Unstructured{Object: m})
		}
		return out, nil
	}
}

// labelsFromSelector 把 "key=value" 拆成 map (derive 只传单一 label=value, 简单解析)。
func labelsFromSelector(s string) (map[string]string, error) {
	for i := 0; i < len(s); i++ {
		if s[i] == '=' {
			return map[string]string{s[:i]: s[i+1:]}, nil
		}
	}
	return map[string]string{}, nil
}
