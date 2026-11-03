// Package controller 实现 projection reconciler: 读 K8s (cache) → 派生 → 写 DDB。
//
// 这是 projection/sync controller — 把 K8s 状态单向投影到 DynamoDB, 不写回 K8s。
// reconcile 不依赖"收到什么事件", 每次都从 cache 读齐当前状态重算 (幂等),
// 故事件顺序无关、CR/Workload 谁先到都正确 (天然消除 read-after-create 竞态)。
package controller

import (
	"context"
	"fmt"
	"sync"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"sigs.k8s.io/controller-runtime/pkg/client"
	ctrllog "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/ddb"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/derive"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"

	"k8s.io/apimachinery/pkg/runtime/schema"
)

// CRReconciler 处理一类 CR (训练/推理/开发机各一个实例)。
type CRReconciler struct {
	// reader 是 cache-backed client (读 watch 的 CR/Workload 走内存 cache, 不打 API)。
	reader client.Reader
	writer *ddb.Writer

	// podLister 按需查 Pod (occupying / 2跳关联)。Pod 不 watch (训练上百且抖动),
	// 故用直连 API 的 client, 不走 cache。由 setup 注入; nil 则 derive 视作无 Pod。
	podLister derive.PodLister

	// 本 reconciler 负责的 CR 类型坐标。
	crGVK schema.GroupVersionKind

	// resource_type 字符串 (train/inference/dev), 写 DDB 的 resource_key 前缀。
	resourceType string

	// 把 CR 解析成 (resourceID, workspaceID); 不同 CR 的 label/兜底规则不同。
	// TODO(你补): 对应 Python resolve_ids (label 优先 + namespace 反推 ws)。
	resolveIDs func(cr *unstructured.Unstructured) (resourceID, workspaceID string, ok bool)

	// idIndex: namespacedName → (ws,id) 的内存索引。每次成功 reconcile 记一条;
	// CR 删除时 cache 已无对象、拿不到 label, 靠此反查 DDB 主键 (方案 A)。
	// 重启后为空 → 重启窗口内的删除靠 10h resync 兜底 (届时 CR 已不在, 不会重记,
	// 但也无法补删 — 可接受: 删除本就由前端 DELETE 接口收口, 本路径是兜底)。
	idIndex sync.Map // key: "ns/name" → value: crIDs
}

// crIDs 是 idIndex 里缓存的 DDB 主键要素。
type crIDs struct {
	ws string
	id string
}

// Reconcile 是核心循环: 读齐 CR + 关联 Workload/Pod → 派生 → 写 DDB。
func (r *CRReconciler) Reconcile(ctx context.Context, reqst reconcile.Request) (reconcile.Result, error) {
	lg := ctrllog.FromContext(ctx)

	// 1. 从 cache 读 CR。NotFound = CR 已删 → 软删 DDB。
	cr := gvk.NewUnstructured(r.crGVK)
	if err := r.reader.Get(ctx, reqst.NamespacedName, cr); err != nil {
		if apierrors.IsNotFound(err) {
			return r.handleDeleted(ctx, reqst)
		}
		return reconcile.Result{}, fmt.Errorf("get CR: %w", err)
	}

	// 2. 解析 ids (拿不到 ws/id → 跳过, 不报错)。
	resID, wsID, ok := r.resolveIDs(cr)
	if !ok {
		lg.V(1).Info("resolve_ids 跳过", "name", cr.GetName())
		return reconcile.Result{}, nil
	}

	// 3. 读关联 Workload (从 cache) + 4. 派生。关联形态三分:
	//    - 训练/开发机: 1 个 CR ≈ 1 个 Workload → fetchWorkload (单数)
	//    - 推理: 多副本每 Pod 一个 Workload → workloadsVia2Hop (复数, aggregateKueueBest 聚合)
	//    - Dynamo: 1 个 DGD → 多 Pod → 多 Workload → fetchWorkloads (复数, 备齐 Pod+Workload 供聚合)
	var status derive.Status
	if r.crGVK.Kind == gvk.DynamoGraph.Kind {
		pods, wls, ferr := r.fetchWorkloads(ctx, cr)
		if ferr != nil {
			return reconcile.Result{}, fmt.Errorf("fetch workloads: %w", ferr)
		}
		status = derive.Derive(ctx, r.crGVK.Kind, derive.Inputs{
			CR:         cr,
			Workloads:  wls,
			DynamoPods: pods,
		})
	} else if r.crGVK.Kind == gvk.Inference.Kind {
		wls, ferr := r.workloadsVia2Hop(ctx, cr, infPodLabelKey)
		if ferr != nil {
			return reconcile.Result{}, fmt.Errorf("fetch workloads: %w", ferr)
		}
		status = derive.Derive(ctx, r.crGVK.Kind, derive.Inputs{
			CR:        cr,
			Workloads: wls,
			Pods:      r.podLister,
		})
	} else if r.crGVK.Kind == gvk.RayJob.Kind {
		// RayJob: Workload 1 跳 (同训练) + RayCluster (occupying 信号)。
		wl, ferr := r.fetchWorkload(ctx, cr)
		if ferr != nil {
			return reconcile.Result{}, fmt.Errorf("fetch workload: %w", ferr)
		}
		rc, ferr := r.fetchRayCluster(ctx, cr)
		if ferr != nil {
			return reconcile.Result{}, fmt.Errorf("fetch raycluster: %w", ferr)
		}
		status = derive.Derive(ctx, r.crGVK.Kind, derive.Inputs{
			CR:         cr,
			Workload:   wl,
			RayCluster: rc,
		})
	} else {
		wl, ferr := r.fetchWorkload(ctx, cr)
		if ferr != nil {
			return reconcile.Result{}, fmt.Errorf("fetch workload: %w", ferr)
		}
		status = derive.Derive(ctx, r.crGVK.Kind, derive.Inputs{
			CR:       cr,
			Workload: wl,
			Pods:     r.podLister,
		})
	}

	// 5. 写 DDB (部分更新 + dedup + active_ws 联动, 在 ddb 包)。
	rv := parseRV(cr.GetResourceVersion())
	t := ddb.Target{WorkspaceID: wsID, ResourceType: r.resourceType, ResourceID: resID, ResourceVersion: rv}
	if err := r.writer.UpsertStatus(ctx, t, status); err != nil {
		return reconcile.Result{}, fmt.Errorf("ddb upsert: %w", err) // 返回 err → work queue 限速重试
	}
	// 记住 name→(ws,id), 供 CR 删除时反查 (那时 cache 已无 label)。
	r.idIndex.Store(reqst.NamespacedName.String(), crIDs{ws: wsID, id: resID})
	lg.V(1).Info("reconciled", "id", resID, "ks", status.KueueStatus, "phase", status.Phase, "active", status.ActiveWS.String())
	return reconcile.Result{}, nil
}

func (r *CRReconciler) handleDeleted(ctx context.Context, reqst reconcile.Request) (reconcile.Result, error) {
	lg := ctrllog.FromContext(ctx)

	// CR 已从 cache 消失, 拿不到 label → 从内存索引反查 (reconcile 时记的)。
	v, ok := r.idIndex.Load(reqst.NamespacedName.String())
	if !ok {
		// 没记录: 从没成功 reconcile 过 (缺 label 被跳过), 或重启丢了索引。
		// DDB 主键无从得知 → 跳过 (删除本由前端 DELETE 接口收口, 本路径是兜底)。
		lg.V(1).Info("handleDeleted 跳过: 无 id 索引", "cr", reqst.NamespacedName.String())
		return reconcile.Result{}, nil
	}
	ids := v.(crIDs)

	// RayJob: phase 保持原样 (CR 被 ttl GC 删, 非用户停止, 见文档 §7); 其余类型标 Stopped。
	keepPhase := r.crGVK.Kind == gvk.RayJob.Kind
	if err := r.writer.MarkDeleted(ctx, ids.ws, r.resourceType, ids.id, keepPhase); err != nil {
		return reconcile.Result{}, fmt.Errorf("ddb mark deleted: %w", err) // 重试
	}
	r.idIndex.Delete(reqst.NamespacedName.String()) // 已处理, 出索引
	lg.V(1).Info("marked deleted", "id", ids.id)
	return reconcile.Result{}, nil
}

// fetchWorkload 读关联 Workload。查不到返回 (nil, nil) — derive 据此冻结或终态短路。
//   - 训练 (1 跳): job-uid = CR.uid, 从 cache List Workload, 取第一个 (1:1)。
//   - 开发机 (2 跳): 按 label 查 Pod → pick 最新 Pod uid → job-uid=该 uid 查 Workload。
//     (推理不走这里: 多副本需全量 Workload, 用 workloadsVia2Hop 复数版。)
func (r *CRReconciler) fetchWorkload(ctx context.Context, cr *unstructured.Unstructured) (*unstructured.Unstructured, error) {
	switch r.crGVK.Kind {
	case gvk.Training.Kind, gvk.RayJob.Kind:
		// 训练/RayJob: Workload owner 直指 CR, job-uid = CR.uid (1:1 单跳)。
		return r.workloadByJobUID(ctx, cr.GetNamespace(), string(cr.GetUID()))
	case gvk.DevInstance.Kind:
		return r.workloadVia2Hop(ctx, cr, devPodLabelKey)
	default:
		return nil, nil
	}
}

// workloadByJobUID: 从 cache 按 job-uid label 查 Workload, 取第一个。
func (r *CRReconciler) workloadByJobUID(ctx context.Context, namespace, jobUID string) (*unstructured.Unstructured, error) {
	if jobUID == "" {
		return nil, nil
	}
	var list unstructured.UnstructuredList
	list.SetGroupVersionKind(gvk.Workload)
	if err := r.reader.List(ctx, &list,
		client.InNamespace(namespace),
		client.MatchingLabels{gvk.LabelJobUID: jobUID},
	); err != nil {
		return nil, err
	}
	if len(list.Items) == 0 {
		return nil, nil
	}
	return &list.Items[0], nil
}

// workloadVia2Hop (开发机): 查 Pod (podLabelKey=CR name) → pick 最新 → 用 Pod uid 查 Workload。
// Pod 从 cache (推理/开发机 Pod 已 watch, 见 main.go 的 !HPJob selector); Workload 也从 cache。
// 单副本时就一个 Pod; 多副本 pickLatestPod 取最近状态变化的 (开发机恒单副本)。
func (r *CRReconciler) workloadVia2Hop(ctx context.Context, cr *unstructured.Unstructured, podLabelKey string) (*unstructured.Unstructured, error) {
	var podList unstructured.UnstructuredList
	podList.SetGroupVersionKind(gvk.Pod)
	if err := r.reader.List(ctx, &podList,
		client.InNamespace(cr.GetNamespace()),
		client.MatchingLabels{podLabelKey: cr.GetName()},
	); err != nil {
		return nil, err
	}
	pods := make([]*unstructured.Unstructured, len(podList.Items))
	for i := range podList.Items {
		pods[i] = &podList.Items[i]
	}
	pod := pickLatestPod(pods)
	if pod == nil {
		return nil, nil // 没 Pod (还没建 / 已停删) → derive 冻结或终态短路
	}
	podUID, _, _ := unstructured.NestedString(pod.Object, "metadata", "uid")
	if podUID == "" {
		return nil, nil
	}
	return r.workloadByJobUID(ctx, cr.GetNamespace(), podUID)
}

// workloadsVia2Hop (推理, 复数版): 查该 CR 的【全部】Pod → uid 集 → 全部对应 Workload。
// 多副本时每副本 Pod 各有一个 Workload (pod 级集成, job-uid=Pod uid), 全量取回供
// aggregateKueueBest 聚合 — 替换旧 pickLatestPod 只取一个的时序巧合 (多副本下
// kueue_status 会随"谁最近变化"在 Admitted/Queued 间摆动)。单副本行为不变。
// 走法与 Dynamo fetchWorkloads 同构, 但 Pod 直接带 app=<CR名> label, 不用经 DGD 归一。
func (r *CRReconciler) workloadsVia2Hop(ctx context.Context, cr *unstructured.Unstructured, podLabelKey string) ([]*unstructured.Unstructured, error) {
	ns := cr.GetNamespace()

	var podList unstructured.UnstructuredList
	podList.SetGroupVersionKind(gvk.Pod)
	if err := r.reader.List(ctx, &podList,
		client.InNamespace(ns),
		client.MatchingLabels{podLabelKey: cr.GetName()},
	); err != nil {
		return nil, err
	}
	uidSet := make(map[string]bool, len(podList.Items))
	for i := range podList.Items {
		if uid := string(podList.Items[i].GetUID()); uid != "" {
			uidSet[uid] = true
		}
	}
	if len(uidSet) == 0 {
		return nil, nil // 无 Pod → 无 Workload (derive 冻结或终态短路)
	}

	// 本 ns 全部 Workload, 内存过滤 job-uid ∈ uidSet (与 Dynamo fetchWorkloads 同款)。
	var wlList unstructured.UnstructuredList
	wlList.SetGroupVersionKind(gvk.Workload)
	if err := r.reader.List(ctx, &wlList, client.InNamespace(ns)); err != nil {
		return nil, err
	}
	var workloads []*unstructured.Unstructured
	for i := range wlList.Items {
		juid := wlList.Items[i].GetLabels()[gvk.LabelJobUID]
		if juid != "" && uidSet[juid] {
			workloads = append(workloads, &wlList.Items[i])
		}
	}
	return workloads, nil
}

// fetchWorkloads (Dynamo 专用): 一个 DGD 对应多 Pod / 多 Workload, 全程走 cache 内存读。
//
// Workload 自身无 DGD 标识 (只有 kueue.x-k8s.io/job-uid = owner Pod uid), 故必须经 Pod:
//  1. list 该 DGD 的全部 Pod (label nvidia.com/dynamo-graph-deployment-name=<DGD名>), 收集 uid;
//  2. list 本 ns 全部 Workload, 内存过滤 job-uid ∈ 上述 uid 集 → 该 DGD 的 Workload。
//
// 返回 (pods, workloads): pods 供派生层判 live pod / 0-pod 终态, workloads 供聚合 kueue_status。
// Dynamo Pod 在 cache 内 (不被 main.go 的 !HPJob selector 挡), 故用 r.reader (cache), 非 podLister。
func (r *CRReconciler) fetchWorkloads(ctx context.Context, cr *unstructured.Unstructured) (
	pods []*unstructured.Unstructured, workloads []*unstructured.Unstructured, err error) {
	ns := cr.GetNamespace()

	// 1. 该 DGD 的全部 Pod。
	var podList unstructured.UnstructuredList
	podList.SetGroupVersionKind(gvk.Pod)
	if err = r.reader.List(ctx, &podList,
		client.InNamespace(ns),
		client.MatchingLabels{gvk.LabelDynamoGraphName: cr.GetName()},
	); err != nil {
		return nil, nil, err
	}
	uidSet := make(map[string]bool, len(podList.Items))
	pods = make([]*unstructured.Unstructured, len(podList.Items))
	for i := range podList.Items {
		pods[i] = &podList.Items[i]
		if uid := string(podList.Items[i].GetUID()); uid != "" {
			uidSet[uid] = true
		}
	}
	if len(uidSet) == 0 {
		return pods, nil, nil // 无 Pod → 无 Workload (派生层据 pods 空 + phase 判终态/冻结)
	}

	// 2. 本 ns 全部 Workload, 内存过滤 job-uid ∈ uidSet (Kueue 只能按自身 label 查, 不支持 uid IN 多值)。
	var wlList unstructured.UnstructuredList
	wlList.SetGroupVersionKind(gvk.Workload)
	if err = r.reader.List(ctx, &wlList, client.InNamespace(ns)); err != nil {
		return nil, nil, err
	}
	for i := range wlList.Items {
		juid := wlList.Items[i].GetLabels()[gvk.LabelJobUID]
		if juid != "" && uidSet[juid] {
			workloads = append(workloads, &wlList.Items[i])
		}
	}
	return pods, workloads, nil
}

// fetchRayCluster (RayJob): 从 cache List 该 RayJob 的 RayCluster
// (label ray.io/originated-from-cr-name=<CR名>; RayCluster 名带随机后缀不能按名 Get)。
// 返回 nil = 已删 (ttl 到期 shutdown) 或还没建 —— 派生层据此判 occupying。
// RayCluster 经 setup.go 的 Owns(RayCluster) 已入 cache, 故走 r.reader (cache) 不打 API。
func (r *CRReconciler) fetchRayCluster(ctx context.Context, cr *unstructured.Unstructured) (*unstructured.Unstructured, error) {
	var list unstructured.UnstructuredList
	list.SetGroupVersionKind(gvk.RayCluster)
	if err := r.reader.List(ctx, &list,
		client.InNamespace(cr.GetNamespace()),
		client.MatchingLabels{gvk.LabelRayOriginatedFromCRName: cr.GetName()},
	); err != nil {
		return nil, err
	}
	if len(list.Items) == 0 {
		return nil, nil
	}
	return &list.Items[0], nil
}
