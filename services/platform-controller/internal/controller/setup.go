package controller

import (
	"fmt"
	"strconv"

	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/discovery"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	ctrllog "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/manager"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/ddb"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/mapping"
)

// watchMode 描述某类 CR 的关联 Workload 事件如何映射回 CR (owner 链形态不同):
//   - watchOwns:   Workload owner 直接是 CR → builder.Owns 框架自动 1 跳映射 (训练)
//   - watchPod2Hop: Workload owner 是 Pod (中间还有 ReplicaSet/Deployment 或 Grove PodClique)
//                   → 走 Watches + mapping.WorkloadToCR (经 owner Pod 读 label 拿 CR name,
//                   跳过中间层)。推理/开发机/Dynamo 均属此类 (实测确认 owner=Pod + Pod 带 CR-name label)。
type watchMode int

const (
	watchOwns watchMode = iota
	watchPod2Hop
	// watchDynamo: Dynamo 专用。除 Watches(Workload) 外, 还 Watches(Pod) —— 一个 DGD 多 Pod/多
	// Workload, 且任务结束时靠"全部 Pod 消失"判 Finished (Workload 删除事件可能因 owner Pod 先删
	// 而漏触发, 见 mapping.PodToCR)。两个 watch 都映射到 reconcile 该 DGD。
	watchDynamo
	// watchRay: RayJob 专用。Owns(Workload) (同训练 1 跳) + 额外 Owns(RayCluster)。
	// RayCluster 是 head+worker Pod 的 owner (ownerRef→RayJob controller=true); ttl(关闭
	// timeout) 到期 KubeRay 只删 RayCluster (级联删 Pod), 其删除事件经 ownerRef 触发 reconcile,
	// 让派生层及时据"RayCluster 已删"翻 active_ws (bob-ray-12 实测: CR+Workload 永久留存,
	// 唯 RayCluster 删除标志资源释放)。
	watchRay
)

// SetupAll 为每种 CR 各注册一路 controller。
//
// CR 自身变化: For(CR) 触发 reconcile (所有类型都有)。
// Workload 变化 → 触发对应 CR 的 reconcile (解决"Workload 变了 CR 没变收不到"痛点),
// 映射方式按 watchMode 区分 (见上)。
//
// 各路共享 mgr 的同一个 cache (informer), 故 CR/Workload/Pod 各只 watch+缓存一次。
//
// 注册前先 discovery 探测 CRD 是否已装: 缺失的路跳过 (warning 日志), 其余照常 —
// 例如集群没装 NVIDIA Dynamo operator 时, dynamo 一路缺 CRD 不能拖死训练/推理/开发机
// (informer 对不存在的 CRD 永远 sync 不完 → manager 启动超时 → CrashLoopBackOff)。
// 跳过后若后续装上 CRD, 需重启 controller Pod 才会开始 watch。
func SetupAll(mgr manager.Manager, writer *ddb.Writer) error {
	lg := ctrllog.Log.WithName("setup")

	disc, err := discovery.NewDiscoveryClientForConfig(mgr.GetConfig())
	if err != nil {
		return fmt.Errorf("build discovery client: %w", err)
	}
	specs := []struct {
		gvkCR        schema.GroupVersionKind
		resourceType string
		controllerNm string
		watch        watchMode
	}{
		{gvk.Training, "train", "training-controller", watchOwns},
		{gvk.Inference, "inference", "inference-controller", watchPod2Hop},
		{gvk.DevInstance, "dev", "devinstance-controller", watchPod2Hop},
		{gvk.DynamoGraph, "dynamo", "dynamo-controller", watchDynamo},
		{gvk.RayJob, "rayjob", "rayjob-controller", watchRay},
	}

	// Pod 直查 (不走 cache, Pod 未 watch); occupying / 2跳关联用。
	podLister := newPodLister(mgr.GetAPIReader())

	for _, sp := range specs {
		ok, err := gvkAvailable(disc, sp.gvkCR)
		if err != nil {
			return fmt.Errorf("discovery check %s: %w", sp.gvkCR, err)
		}
		if !ok {
			lg.Info("CRD not installed, skipping controller (install the CRD and restart to enable)",
				"controller", sp.controllerNm, "gvk", sp.gvkCR.String())
			continue
		}

		r := &CRReconciler{
			reader:       mgr.GetCache(),
			writer:       writer,
			podLister:    podLister,
			crGVK:        sp.gvkCR,
			resourceType: sp.resourceType,
			resolveIDs:   resolveIDsFor(sp.gvkCR.Kind),
		}

		b := builder.ControllerManagedBy(mgr).
			Named(sp.controllerNm).
			For(gvk.NewUnstructured(sp.gvkCR))

		switch sp.watch {
		case watchOwns:
			// 训练: Workload owner 直接是 CR → Owns 自动映射。
			b = b.Owns(gvk.NewUnstructured(gvk.Workload))
		case watchPod2Hop:
			// 推理/开发机: Workload owner 是 Pod → 手写映射 (经 Pod label 拿 CR name)。
			b = b.Watches(
				gvk.NewUnstructured(gvk.Workload),
				handler.EnqueueRequestsFromMapFunc(
					mapping.WorkloadToCR(mgr.GetCache(), sp.gvkCR.Kind),
				),
			)
		case watchDynamo:
			// Dynamo: 同 pod2hop 的 Workload 映射, 额外 Watches(Pod) 让"全部 Pod 消失"可靠触发 reconcile。
			b = b.Watches(
				gvk.NewUnstructured(gvk.Workload),
				handler.EnqueueRequestsFromMapFunc(
					mapping.WorkloadToCR(mgr.GetCache(), sp.gvkCR.Kind),
				),
			).Watches(
				gvk.NewUnstructured(gvk.Pod),
				handler.EnqueueRequestsFromMapFunc(
					mapping.PodToCR(sp.gvkCR.Kind),
				),
			)
		case watchRay:
			// RayJob: Workload 1 跳 (同训练) + RayCluster (ttl 到期删除信号)。
			b = b.Owns(gvk.NewUnstructured(gvk.Workload)).
				Owns(gvk.NewUnstructured(gvk.RayCluster))
		}

		if err := b.Complete(r); err != nil {
			return err
		}
	}

	// ── 第 5 路: llm-d (双资源合成 key, 形态与上四路不同故单独注册) ──
	// 无 For(): LWS/Deployment/Workload 三路 Watches 全映射到 Request{ns, llmd-id}
	// (req.Name 即 DDB resource_id)。Reconcile 按 llmd-id label List 双资源。
	// 与上四路同样先探测 CRD: 集群没装 LWS operator 时跳过, 不拖死其余各路。
	lwsOK, err := gvkAvailable(disc, gvk.LlmdLWS)
	if err != nil {
		return fmt.Errorf("discovery check %s: %w", gvk.LlmdLWS, err)
	}
	// 用 if 包裹而非 !lwsOK 提前 return: 保持"新增控制器往后追加"可扩展 (提前 return 会
	// 在 LWS CRD 缺失时静默跳过后续任何新路)。
	if lwsOK {
		llmdR := &LlmdReconciler{reader: mgr.GetCache(), writer: writer}
		if err := builder.ControllerManagedBy(mgr).
			Named("llmd-controller").
			Watches(gvk.NewUnstructured(gvk.LlmdLWS),
				handler.EnqueueRequestsFromMapFunc(mapping.LlmdObjectToKey())).
			Watches(gvk.NewUnstructured(gvk.Deployment),
				handler.EnqueueRequestsFromMapFunc(mapping.LlmdObjectToKey())).
			Watches(gvk.NewUnstructured(gvk.Workload),
				handler.EnqueueRequestsFromMapFunc(mapping.LlmdWorkloadToKey(mgr.GetCache()))).
			Complete(llmdR); err != nil {
			return err
		}
	} else {
		lg.Info("CRD not installed, skipping controller (install the CRD and restart to enable)",
			"controller", "llmd-controller", "gvk", gvk.LlmdLWS.String())
	}
	return nil
}

func parseRV(s string) int64 {
	n, _ := strconv.ParseInt(s, 10, 64)
	return n
}
