package mapping

import (
	"context"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// mkU: unstructured 夹具 (apiVersion/kind/ns/name/labels/ownerRefs)。
func mkU(apiVersion, kind, ns, name string, labels map[string]string, owners []metav1.OwnerReference) *unstructured.Unstructured {
	u := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": apiVersion, "kind": kind,
		"metadata": map[string]any{"namespace": ns, "name": name},
	}}
	if labels != nil {
		u.SetLabels(labels)
	}
	if owners != nil {
		u.SetOwnerReferences(owners)
	}
	return u
}

// LlmdObjectToKey: LWS/Deployment 事件 → 读自身 llmd-id label → Request{ns, llmd-id}。
func TestLlmdObjectToKey(t *testing.T) {
	fn := LlmdObjectToKey()

	lws := mkU("leaderworkerset.x-k8s.io/v1", "LeaderWorkerSet", "ns1", "t1-multi",
		map[string]string{gvk.LabelLlmdID: "id-123"}, nil)
	reqs := fn(context.Background(), lws)
	if len(reqs) != 1 || reqs[0].Name != "id-123" || reqs[0].Namespace != "ns1" {
		t.Fatalf("reqs = %v, want [{ns1 id-123}]", reqs)
	}

	// 无 llmd-id label (手工 kubectl 建的, 如 llmd-b) → nil 过滤。
	plain := mkU("apps/v1", "Deployment", "ns1", "other", nil, nil)
	if got := fn(context.Background(), plain); got != nil {
		t.Fatalf("无 label 应过滤, got %v", got)
	}
}

// LlmdWorkloadToKey: Workload 事件 → owner (LWS 或 Pod) → 读 owner 的 llmd-id → key。
func TestLlmdWorkloadToKey(t *testing.T) {
	scheme := runtime.NewScheme()
	scheme.AddKnownTypeWithName(gvk.LlmdLWS, &unstructured.Unstructured{})
	scheme.AddKnownTypeWithName(gvk.LlmdLWS.GroupVersion().WithKind("LeaderWorkerSetList"), &unstructured.UnstructuredList{})
	_ = corev1.AddToScheme(scheme)

	lws := mkU("leaderworkerset.x-k8s.io/v1", "LeaderWorkerSet", "ns1", "t1-multi",
		map[string]string{gvk.LabelLlmdID: "id-123"}, nil)
	userLws := mkU("leaderworkerset.x-k8s.io/v1", "LeaderWorkerSet", "ns1", "user-lws", nil, nil)
	gwPod := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{
		Namespace: "ns1", Name: "t1-gateway-abc", UID: types.UID("gwpod-uid"),
		Labels: map[string]string{gvk.LabelLlmdID: "id-123"},
	}}
	infPod := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{
		Namespace: "ns1", Name: "inf-pod", UID: types.UID("infpod-uid"),
		Labels: map[string]string{"app": "inf1"}, // 无 llmd-id
	}}
	reader := fake.NewClientBuilder().WithScheme(scheme).WithObjects(lws, userLws, gwPod, infPod).Build()
	fn := LlmdWorkloadToKey(reader)

	// 分支 1: LWS Workload (ownerRef 含 LeaderWorkerSet, 自身无 label — v0.12.0 实证)。
	wlLws := mkU("kueue.x-k8s.io/v1beta1", "Workload", "ns1", "leaderworkerset-t1-multi-0-x", nil,
		[]metav1.OwnerReference{{APIVersion: "leaderworkerset.x-k8s.io/v1", Kind: "LeaderWorkerSet", Name: "t1-multi", UID: "lws-uid"}})
	reqs := fn(context.Background(), wlLws)
	if len(reqs) != 1 || reqs[0].Name != "id-123" {
		t.Fatalf("LWS Workload 映射 = %v, want id-123", reqs)
	}

	// 分支 2: gateway Workload (pod 级, ownerRef 是 Pod)。
	wlGw := mkU("kueue.x-k8s.io/v1beta1", "Workload", "ns1", "pod-t1-gateway-abc-x", nil,
		[]metav1.OwnerReference{{APIVersion: "v1", Kind: "Pod", Name: "t1-gateway-abc", UID: "gwpod-uid"}})
	reqs = fn(context.Background(), wlGw)
	if len(reqs) != 1 || reqs[0].Name != "id-123" {
		t.Fatalf("gateway Workload 映射 = %v, want id-123", reqs)
	}

	// 无关 Workload: owner Pod 无 llmd-id (推理/开发机) → nil。
	wlInf := mkU("kueue.x-k8s.io/v1beta1", "Workload", "ns1", "pod-inf-x", nil,
		[]metav1.OwnerReference{{APIVersion: "v1", Kind: "Pod", Name: "inf-pod", UID: "infpod-uid"}})
	if got := fn(context.Background(), wlInf); got != nil {
		t.Fatalf("无关 Workload 应过滤, got %v", got)
	}

	// owner 已删 (cache 读不到) → nil, 无害 (owner 自己的删除事件走 LlmdObjectToKey 触发同 key)。
	wlGone := mkU("kueue.x-k8s.io/v1beta1", "Workload", "ns1", "leaderworkerset-gone-0-x", nil,
		[]metav1.OwnerReference{{APIVersion: "leaderworkerset.x-k8s.io/v1", Kind: "LeaderWorkerSet", Name: "gone", UID: "gone-uid"}})
	if got := fn(context.Background(), wlGone); got != nil {
		t.Fatalf("owner 已删应过滤, got %v", got)
	}

	// owner LWS 在 cache 但无 llmd-id label (用户自部署 LWS) → nil 过滤。
	wlUser := mkU("kueue.x-k8s.io/v1beta1", "Workload", "ns1", "leaderworkerset-user-lws-0-x", nil,
		[]metav1.OwnerReference{{APIVersion: "leaderworkerset.x-k8s.io/v1", Kind: "LeaderWorkerSet", Name: "user-lws", UID: "user-uid"}})
	if got := fn(context.Background(), wlUser); got != nil {
		t.Fatalf("无 llmd-id 的 LWS 应过滤, got %v", got)
	}
}
