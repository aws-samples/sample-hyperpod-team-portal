package controller

import (
	"context"
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// mkPod / mkWL: unstructured 测试夹具。
func mkPod(ns, name, uid string, labels map[string]any) *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "v1", "kind": "Pod",
		"metadata": map[string]any{"namespace": ns, "name": name, "uid": uid, "labels": labels},
	}}
}

func mkWL(ns, name, jobUID string) *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "kueue.x-k8s.io/v1beta1", "kind": "Workload",
		"metadata": map[string]any{"namespace": ns, "name": name,
			"labels": map[string]any{gvk.LabelJobUID: jobUID}},
	}}
}

func fakeReader(objs ...*unstructured.Unstructured) *CRReconciler {
	scheme := runtime.NewScheme()
	scheme.AddKnownTypeWithName(gvk.Pod, &unstructured.Unstructured{})
	scheme.AddKnownTypeWithName(gvk.Pod.GroupVersion().WithKind("PodList"), &unstructured.UnstructuredList{})
	scheme.AddKnownTypeWithName(gvk.Workload, &unstructured.Unstructured{})
	scheme.AddKnownTypeWithName(gvk.Workload.GroupVersion().WithKind("WorkloadList"), &unstructured.UnstructuredList{})
	b := fake.NewClientBuilder().WithScheme(scheme)
	for _, o := range objs {
		b = b.WithObjects(o)
	}
	return &CRReconciler{reader: b.Build(), crGVK: gvk.Inference}
}

// workloadsVia2Hop (推理多副本): 全部 Pod → uid 集 → 全部对应 Workload (复数)。
// 修 pickLatestPod 只取一个 Pod/Workload 的旧行为。
func TestWorkloadsVia2Hop(t *testing.T) {
	cr := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "inference.sagemaker.aws.amazon.com/v1", "kind": "InferenceEndpointConfig",
		"metadata": map[string]any{"namespace": "ns1", "name": "inf1"},
	}}
	cr.SetGroupVersionKind(gvk.Inference)

	r := fakeReader(
		mkPod("ns1", "inf1-pod-a", "uid-a", map[string]any{"app": "inf1"}),
		mkPod("ns1", "inf1-pod-b", "uid-b", map[string]any{"app": "inf1"}),
		mkPod("ns1", "other-pod", "uid-x", map[string]any{"app": "other"}), // 无关 Pod
		mkWL("ns1", "wl-a", "uid-a"),
		mkWL("ns1", "wl-b", "uid-b"),
		mkWL("ns1", "wl-x", "uid-x"), // 无关 Workload
	)

	wls, err := r.workloadsVia2Hop(context.Background(), cr, infPodLabelKey)
	if err != nil {
		t.Fatalf("err = %v", err)
	}
	if len(wls) != 2 {
		t.Fatalf("len(workloads) = %d, want 2 (两副本各一, 排除无关)", len(wls))
	}
	got := map[string]bool{}
	for _, w := range wls {
		got[w.GetName()] = true
	}
	if !got["wl-a"] || !got["wl-b"] {
		t.Errorf("workloads = %v, want [wl-a wl-b]", got)
	}

	// 无 Pod → 空集 (nil), 无错误 (derive 据此冻结/终态短路)。
	crNone := cr.DeepCopy()
	crNone.SetName("no-pods")
	wls, err = r.workloadsVia2Hop(context.Background(), crNone, infPodLabelKey)
	if err != nil || len(wls) != 0 {
		t.Errorf("无 Pod 应返回空集无错误, got len=%d err=%v", len(wls), err)
	}
}
