package controller

import (
	"context"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/ddb"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

const (
	testLlmdID = "id-123"
	testWsID   = "ws-1"
)

func newLlmdScheme() *runtime.Scheme {
	s := runtime.NewScheme()
	for _, g := range []struct {
		item schema.GroupVersionKind
		list string
	}{
		{gvk.LlmdLWS, "LeaderWorkerSetList"},
		{gvk.Deployment, "DeploymentList"},
		{gvk.Workload, "WorkloadList"},
		{gvk.Pod, "PodList"},
	} {
		s.AddKnownTypeWithName(g.item, &unstructured.Unstructured{})
		s.AddKnownTypeWithName(g.item.GroupVersion().WithKind(g.list), &unstructured.UnstructuredList{})
	}
	return s
}

func mkLlmdLWSObj() *unstructured.Unstructured {
	u := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "leaderworkerset.x-k8s.io/v1", "kind": "LeaderWorkerSet",
		"metadata": map[string]any{
			"namespace": "ns1", "name": "t1-multi", "uid": "lws-uid", "resourceVersion": "100",
			"labels": map[string]any{
				gvk.LabelLlmdID: testLlmdID, gvk.LabelLlmdWorkspaceID: testWsID,
			},
		},
		"status": map[string]any{"conditions": []any{
			map[string]any{"type": "Available", "status": "True"},
		}},
	}}
	return u
}

func mkLlmdGwObj() *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "apps/v1", "kind": "Deployment",
		"metadata": map[string]any{
			"namespace": "ns1", "name": "t1-gateway", "uid": "gw-uid", "resourceVersion": "90",
			"labels": map[string]any{
				gvk.LabelLlmdID: testLlmdID, gvk.LabelLlmdWorkspaceID: testWsID,
			},
		},
		"status": map[string]any{"conditions": []any{
			map[string]any{"type": "Available", "status": "True"},
		}},
	}}
}

// mkLlmdWLObj: withLwsOwner → LWS Workload (ownerRef, 无 label — v0.12.0 实证);
// jobUID 非空 → gateway pod 级 Workload (job-uid label)。
func mkLlmdWLObj(name string, withLwsOwner bool, jobUID string) *unstructured.Unstructured {
	u := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "kueue.x-k8s.io/v1beta1", "kind": "Workload",
		"metadata": map[string]any{"namespace": "ns1", "name": name, "uid": "u-" + name},
		"status": map[string]any{"conditions": []any{
			map[string]any{"type": "QuotaReserved", "status": "True"},
			map[string]any{"type": "Admitted", "status": "True"},
		}},
	}}
	if withLwsOwner {
		u.SetOwnerReferences([]metav1.OwnerReference{{
			APIVersion: "leaderworkerset.x-k8s.io/v1", Kind: "LeaderWorkerSet",
			Name: "t1-multi", UID: types.UID("lws-uid"),
		}})
	}
	if jobUID != "" {
		u.SetLabels(map[string]string{gvk.LabelJobUID: jobUID})
	}
	return u
}

// mkGwPodObj: gateway Pod。用 unstructured (非 typed corev1.Pod) — scheme 里 Pod 已按
// unstructured 注册, 再 corev1.AddToScheme 会 double-register panic; 生产 cache 对
// unstructured List 两者皆服务, 实现不变, 只调测试夹具 (与 associate_test.go 同款)。
func mkGwPodObj() *unstructured.Unstructured {
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "v1", "kind": "Pod",
		"metadata": map[string]any{
			"namespace": "ns1", "name": "t1-gateway-abc", "uid": "gwpod-uid",
			"labels": map[string]any{gvk.LabelLlmdID: testLlmdID},
		},
	}}
}

func newLlmdR(objs ...client.Object) *LlmdReconciler {
	b := fake.NewClientBuilder().WithScheme(newLlmdScheme())
	if len(objs) > 0 {
		b = b.WithObjects(objs...)
	}
	return &LlmdReconciler{reader: b.Build(), writer: &ddb.Writer{DryRun: true}}
}

func TestLlmdReconcile(t *testing.T) {
	rq := reconcile.Request{NamespacedName: client.ObjectKey{Namespace: "ns1", Name: testLlmdID}}

	t.Run("运行态: 双资源在 + 两类 Workload → 无错", func(t *testing.T) {
		r := newLlmdR(
			mkLlmdLWSObj(), mkLlmdGwObj(), mkGwPodObj(),
			mkLlmdWLObj("lws-w0", true, ""),
			mkLlmdWLObj("gw-w", false, "gwpod-uid"),
			mkLlmdWLObj("other-w", false, "unrelated-uid"), // 无关 (推理等) 不误取
		)
		if _, err := r.Reconcile(context.Background(), rq); err != nil {
			t.Fatalf("err = %v", err)
		}
		// wsIndex 记住 ws
		if v, ok := r.wsIndex.Load("ns1/" + testLlmdID); !ok || v.(string) != testWsID {
			t.Fatalf("wsIndex = %v/%v, want %s", v, ok, testWsID)
		}
	})

	t.Run("双资源都无 + 无 wsIndex → 跳过不报错", func(t *testing.T) {
		r := newLlmdR()
		if _, err := r.Reconcile(context.Background(), rq); err != nil {
			t.Fatalf("应跳过, err = %v", err)
		}
	})

	t.Run("半删态: LWS 无 gateway 在 → 从 gateway label 解析 ws", func(t *testing.T) {
		r := newLlmdR(mkLlmdGwObj())
		if _, err := r.Reconcile(context.Background(), rq); err != nil {
			t.Fatalf("err = %v", err)
		}
		if _, ok := r.wsIndex.Load("ns1/" + testLlmdID); !ok {
			t.Fatal("wsIndex 应记住 ws (从 gateway label)")
		}
	})

	t.Run("双资源都无但 wsIndex 有 → 走终态写 (无错)", func(t *testing.T) {
		r := newLlmdR()
		r.wsIndex.Store("ns1/"+testLlmdID, testWsID)
		if _, err := r.Reconcile(context.Background(), rq); err != nil {
			t.Fatalf("终态写应成功, err = %v", err)
		}
		if _, ok := r.wsIndex.Load("ns1/" + testLlmdID); ok {
			t.Fatal("终态写后应出 wsIndex")
		}
	})
}

func TestLlmdFetchHelpers(t *testing.T) {
	r := newLlmdR(
		mkLlmdLWSObj(), mkGwPodObj(),
		mkLlmdWLObj("lws-w0", true, ""),
		mkLlmdWLObj("lws-w1", true, ""),
		mkLlmdWLObj("gw-w", false, "gwpod-uid"),
		mkLlmdWLObj("noise", false, "other-uid"),
	)
	ctx := context.Background()

	wls, err := r.workloadsByOwnerUID(ctx, "ns1", "lws-uid")
	if err != nil || len(wls) != 2 {
		t.Fatalf("workloadsByOwnerUID = %d,%v want 2", len(wls), err)
	}
	gwls, err := r.gatewayWorkloads(ctx, "ns1", testLlmdID)
	if err != nil || len(gwls) != 1 || gwls[0].GetName() != "gw-w" {
		t.Fatalf("gatewayWorkloads = %v,%v want [gw-w]", gwls, err)
	}
}
