package controller

import (
	"context"
	"fmt"
	"sync"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"
	ctrllog "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/ddb"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/derive"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// LlmdReconciler: llm-d 双资源任务 (LWS + gateway Deployment) 的合成 key reconciler。
//
// 与四路 CRReconciler 的形态差异:
//   - 无 For(): 三路 Watches 全映射到 Request{ns, llmd-id} (mapping.LlmdObjectToKey /
//     LlmdWorkloadToKey), req.Name 即 DDB resource_id, 无需 resolveIDs。
//   - Reconcile 按 llmd-id label List 双资源 (非 Get by name), List 空 = 该资源已删
//     (LWS 无自行终止路径, 删除是唯一终态; derive 转为 LwsDeleted/GatewayDeleted →
//     writer 写 *_deleted_at, 双双齐才摘 active_ws)。
//   - 任一幸存资源的任何事件 (含 resync) 都触发全量重估 → 半删态跨重启自愈。
type LlmdReconciler struct {
	reader client.Reader
	writer *ddb.Writer

	// wsIndex: "ns/llmd-id" → workspace_id。正常路径 ws 从幸存资源 label 读;
	// 双资源都删的 reconcile (最后一次) 靠此写终态。重启丢失时该次跳过 —
	// 兜底与四路一致: 前端 DELETE API 直写 DDB 收口。
	wsIndex sync.Map
}

// Reconcile: List 双资源 → 取两类 Workload → deriveLlmd → 写 DDB。
func (r *LlmdReconciler) Reconcile(ctx context.Context, req reconcile.Request) (reconcile.Result, error) {
	lg := ctrllog.FromContext(ctx)
	ns, llmdID := req.Namespace, req.Name

	// 1. List 双资源 (llmd-id label)。空 = 已删。
	lws, err := r.oneByLlmdID(ctx, gvk.LlmdLWS, ns, llmdID)
	if err != nil {
		return reconcile.Result{}, fmt.Errorf("list lws: %w", err)
	}
	gw, err := r.oneByLlmdID(ctx, gvk.Deployment, ns, llmdID)
	if err != nil {
		return reconcile.Result{}, fmt.Errorf("list gateway deploy: %w", err)
	}

	// 2. workspace_id: 幸存资源 label 优先, 都没了用 wsIndex。
	ws := llmdLabelOf(lws, gvk.LabelLlmdWorkspaceID)
	if ws == "" {
		ws = llmdLabelOf(gw, gvk.LabelLlmdWorkspaceID)
	}
	idxKey := ns + "/" + llmdID
	if ws == "" {
		v, ok := r.wsIndex.Load(idxKey)
		if !ok {
			lg.V(1).Info("llmd 跳过: 双资源均无且无 ws 索引", "llmdID", llmdID)
			return reconcile.Result{}, nil
		}
		ws = v.(string)
	} else {
		r.wsIndex.Store(idxKey, ws)
	}

	// 3. 两类 Workload (形态不同, 勿混):
	//    LWS Workload: v0.12.0 无 label → ownerRef.uid == LWS.uid 过滤;
	//    gateway Workload: pod 级, 有 job-uid label → 经 gateway Pod (llmd-id label) 2 跳。
	var lwsWls, gwWls []*unstructured.Unstructured
	if lws != nil {
		if lwsWls, err = r.workloadsByOwnerUID(ctx, ns, string(lws.GetUID())); err != nil {
			return reconcile.Result{}, fmt.Errorf("fetch lws workloads: %w", err)
		}
	}
	if gw != nil {
		if gwWls, err = r.gatewayWorkloads(ctx, ns, llmdID); err != nil {
			return reconcile.Result{}, fmt.Errorf("fetch gateway workloads: %w", err)
		}
	}

	// 4. 派生 + 5. 写 DDB。rv 取双资源较大者 (同集群 etcd, max 单调);
	//    双无时 rv=0, 终态字段靠 ks/gks 旁路放行。
	status := derive.Derive(ctx, gvk.LlmdLWS.Kind, derive.Inputs{
		LWS: lws, Workloads: lwsWls,
		GatewayDeploy: gw, GatewayWorkloads: gwWls,
	})
	rv := llmdMaxRV(lws, gw)
	t := ddb.Target{WorkspaceID: ws, ResourceType: "llmd", ResourceID: llmdID, ResourceVersion: rv}
	if err := r.writer.UpsertStatus(ctx, t, status); err != nil {
		return reconcile.Result{}, fmt.Errorf("ddb upsert: %w", err)
	}
	// 双资源均删且终态已写 → 出索引 (防长期运行下 wsIndex 无界增长)。
	// 之后若再触发同 key (不可能有新事件源, 但 resync 兜底): 双无+无索引 → 跳过, 无害。
	if status.LwsDeleted && status.GatewayDeleted {
		r.wsIndex.Delete(idxKey)
	}
	lg.V(1).Info("llmd reconciled", "id", llmdID, "phase", status.Phase,
		"ks", status.KueueStatus, "gwKs", status.GatewayKueueStatus, "active", status.ActiveWS)
	return reconcile.Result{}, nil
}

// oneByLlmdID: List 该 GVK 中带 llmd-id=<id> 的对象取第一个 (设计上 1 任务 1 LWS 1 gateway;
// >1 属平台创建 bug, 取第一个容忍)。空 → nil (= 已删信号)。
func (r *LlmdReconciler) oneByLlmdID(ctx context.Context, g schema.GroupVersionKind, ns, id string) (*unstructured.Unstructured, error) {
	var list unstructured.UnstructuredList
	list.SetGroupVersionKind(g)
	if err := r.reader.List(ctx, &list,
		client.InNamespace(ns), client.MatchingLabels{gvk.LabelLlmdID: id}); err != nil {
		return nil, err
	}
	if len(list.Items) == 0 {
		return nil, nil
	}
	return &list.Items[0], nil
}

// workloadsByOwnerUID: 本 ns 全部 Workload, 内存过滤 ownerRef.uid == ownerUID。
// (LWS Workload 无任何 label — Kueue v0.12.0 实证, 只能全量过滤; Workload 在 cache, 内存读。)
func (r *LlmdReconciler) workloadsByOwnerUID(ctx context.Context, ns, ownerUID string) ([]*unstructured.Unstructured, error) {
	var list unstructured.UnstructuredList
	list.SetGroupVersionKind(gvk.Workload)
	if err := r.reader.List(ctx, &list, client.InNamespace(ns)); err != nil {
		return nil, err
	}
	var out []*unstructured.Unstructured
	for i := range list.Items {
		for _, ref := range list.Items[i].GetOwnerReferences() {
			if string(ref.UID) == ownerUID {
				out = append(out, &list.Items[i])
				break
			}
		}
	}
	return out, nil
}

// gatewayWorkloads: gateway Pod (llmd-id label, 已在 !HPJob cache) → uid 集 →
// job-uid ∈ 集 的 Workload。LWS 的 Pod 若也带 llmd-id 亦无害: LWS Workload 无
// job-uid label, 过滤不会误中 (与 workloadsVia2Hop 同款套路)。
func (r *LlmdReconciler) gatewayWorkloads(ctx context.Context, ns, llmdID string) ([]*unstructured.Unstructured, error) {
	var pods unstructured.UnstructuredList
	pods.SetGroupVersionKind(gvk.Pod)
	if err := r.reader.List(ctx, &pods,
		client.InNamespace(ns), client.MatchingLabels{gvk.LabelLlmdID: llmdID}); err != nil {
		return nil, err
	}
	uidSet := make(map[string]bool, len(pods.Items))
	for i := range pods.Items {
		if uid := string(pods.Items[i].GetUID()); uid != "" {
			uidSet[uid] = true
		}
	}
	if len(uidSet) == 0 {
		return nil, nil
	}
	var wls unstructured.UnstructuredList
	wls.SetGroupVersionKind(gvk.Workload)
	if err := r.reader.List(ctx, &wls, client.InNamespace(ns)); err != nil {
		return nil, err
	}
	var out []*unstructured.Unstructured
	for i := range wls.Items {
		if juid := wls.Items[i].GetLabels()[gvk.LabelJobUID]; juid != "" && uidSet[juid] {
			out = append(out, &wls.Items[i])
		}
	}
	return out, nil
}

// ── 辅助 ──

func llmdLabelOf(u *unstructured.Unstructured, key string) string {
	if u == nil {
		return ""
	}
	return u.GetLabels()[key]
}

func llmdMaxRV(a, b *unstructured.Unstructured) int64 {
	var m int64
	if a != nil {
		if v := parseRV(a.GetResourceVersion()); v > m {
			m = v
		}
	}
	if b != nil {
		if v := parseRV(b.GetResourceVersion()); v > m {
			m = v
		}
	}
	return m
}
