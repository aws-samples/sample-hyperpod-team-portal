package controller

import (
	"bytes"
	"context"
	"log"
	"os"
	"strings"
	"testing"

	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/ddb"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// handleDeleted 两分支:
//   - idIndex 有记录 → 调 MarkDeleted (DryRun 下只 log, 不碰 client) 且出索引
//   - idIndex 无记录 → 跳过, 无错误
//
// 用 DryRun writer (client=nil): MarkDeleted 在用 client 前 return, 故安全无需真 DDB。
func TestHandleDeleted(t *testing.T) {
	w := &ddb.Writer{DryRun: true} // client nil: DryRun 分支不触达
	r := &CRReconciler{writer: w, resourceType: "inference"}

	req := reconcile.Request{NamespacedName: client.ObjectKey{Namespace: "ns1", Name: "cr1"}}

	// 分支 1: 无索引 → skip, 不报错。
	if _, err := r.handleDeleted(context.Background(), req); err != nil {
		t.Fatalf("无索引应跳过, 得到 err=%v", err)
	}

	// 分支 2: 有索引 → MarkDeleted + 出索引。
	r.idIndex.Store(req.NamespacedName.String(), crIDs{ws: "ws1", id: "id1"})
	if _, err := r.handleDeleted(context.Background(), req); err != nil {
		t.Fatalf("有索引应成功, 得到 err=%v", err)
	}
	if _, ok := r.idIndex.Load(req.NamespacedName.String()); ok {
		t.Fatal("处理后应出索引, 但仍在")
	}
}

// handleDeleted 按 crGVK 路由 keepPhase 到 MarkDeleted:
//   - RayJob → keepPhase=true (phase 保持原样, CR 由 ttl GC 删除, 见 §7)
//   - 其余类型 → keepPhase=false (额外标 phase=Stopped)
//
// buildMarkDeleted 已对两 bool 单测; 这里补断言 reconciler 确实按 kind 传对了值。
// 观测点: DryRun 的 MarkDeleted 会 log "keepPhase=%v", 捕获 log 输出即可 (无需 client)。
func TestHandleDeletedKeepPhaseByKind(t *testing.T) {
	cases := []struct {
		name     string
		crGVK    schema.GroupVersionKind
		wantKeep string // "keepPhase=true" / "keepPhase=false"
	}{
		{"RayJob 保持 phase", gvk.RayJob, "keepPhase=true"},
		{"训练 标 Stopped", gvk.Training, "keepPhase=false"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			log.SetOutput(&buf)
			t.Cleanup(func() { log.SetOutput(os.Stderr) })

			w := &ddb.Writer{DryRun: true} // client nil: DryRun 分支不触达
			r := &CRReconciler{writer: w, resourceType: "train", crGVK: tc.crGVK}
			req := reconcile.Request{NamespacedName: client.ObjectKey{Namespace: "ns1", Name: "cr1"}}
			r.idIndex.Store(req.NamespacedName.String(), crIDs{ws: "ws1", id: "id1"})

			if _, err := r.handleDeleted(context.Background(), req); err != nil {
				t.Fatalf("handleDeleted 应成功, 得到 err=%v", err)
			}

			out := buf.String()
			if !strings.Contains(out, tc.wantKeep) {
				t.Fatalf("kind=%s 应传 %s, 但 log 未含; 实际 log=%q", tc.crGVK.Kind, tc.wantKeep, out)
			}
		})
	}
}
