// Package mapping 把"关联资源 (Workload) 变化"映射回"该 reconcile 哪个 CR"。
//
// 为什么需要: controller 的 reconcile 以 CR 为单位, 但 Workload 的 watch 事件给的是
// Workload 自己。要算出它属于哪个 CR, 才能触发那个 CR 的 reconcile (解决"Workload
// 变了但 CR 没变收不到事件"的痛点)。
//
// 真实 owner 链 (2026-06 实测 hyperpod-ns-demo 确认):
//   训练:     Workload --owner--> HyperPodPyTorchJob(CR)        1 跳
//             → 训练不走本包, setup 里直接用 builder.Owns 让框架自动映射。
//   推理/开发机: Workload --owner--> Pod --owner--> ReplicaSet --> Deployment --> CR
//             owner 链 4+ 跳太长太脆。但 Pod 上带 label 直接标识 CR:
//               推理:  app=<CR name>                              (= InferenceEndpointConfig.name)
//               开发机: workspace.jupyter.org/workspace-name=<CR name> (= Workspace.name)
//             故走 "Workload→owner Pod (1层) → 读 Pod label = CR name", 跳过中间层。
//             与现有 Python informer 的 label 关联逻辑一致。
//
// 无关 Workload (如 fsx-admin 系统组件) 的 owner Pod 没有上述 label → 返回 nil,
// 天然被过滤掉, 不会误触发。
package mapping

import (
	"context"

	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// 推理/开发机 Pod 上标识所属 CR name 的 label key (实测确认)。
const (
	LabelInferenceCRName = "app"                                    // 推理 Pod: app=<CR name>
	LabelDevCRName       = "workspace.jupyter.org/workspace-name"   // 开发机 Pod: =<CR name>
	LabelDynamoCRName    = "nvidia.com/dynamo-graph-deployment-name" // Dynamo Pod: =<DGD name> (实测)
)

// CRNameLabelFor 返回某类 CR 在其 Pod 上标识 CR name 的 label key; 不支持的类型返 ""。
// (训练不走本包, 无需在此。)
func CRNameLabelFor(crKind string) string {
	switch crKind {
	case "InferenceEndpointConfig":
		return LabelInferenceCRName
	case "Workspace":
		return LabelDevCRName
	case "DynamoGraphDeployment":
		return LabelDynamoCRName
	default:
		return ""
	}
}

// WorkloadToCR 给 builder.Watches 用: 收到 Workload 变化 → 返回要 reconcile 的 CR。
// 仅用于推理/开发机 (它们的 Workload owner 是 Pod); 训练用 builder.Owns 不走这里。
//
// reader: cache-backed client (读 Pod 走内存 cache, 不打 API)。
// crKind: 该路 controller 负责的 CR Kind (InferenceEndpointConfig / Workspace)。
func WorkloadToCR(reader client.Reader, crKind string) func(context.Context, client.Object) []reconcile.Request {
	labelKey := CRNameLabelFor(crKind)
	return func(ctx context.Context, obj client.Object) []reconcile.Request {
		if labelKey == "" {
			return nil // 不支持的 CR 类型 (训练不该走这)
		}
		// 1. Workload → owner Pod (1 层, 实测 Workload owner 直接是 Pod)。
		podRef := ownerOfKind(obj, "Pod")
		if podRef == nil {
			return nil // 不是 Pod-owned (训练的 Workload owner 是 CR; 或无关)
		}
		// 2. 从 cache 读该 Pod (Pod 与 Workload 同 namespace)。
		var pod corev1.Pod
		key := client.ObjectKey{Namespace: obj.GetNamespace(), Name: podRef.Name}
		if err := reader.Get(ctx, key, &pod); err != nil {
			return nil // Pod 读不到 (已删/cache 未同步) → 跳过, 下次事件再触发
		}
		// 3. Pod label 取 CR name; 没有 → 无关 Workload (如 fsx-admin), 过滤。
		crName := pod.GetLabels()[labelKey]
		if crName == "" {
			return nil
		}
		// 4. reconcile 那个 CR (CR 与 Workload 同 namespace)。
		return []reconcile.Request{req(obj.GetNamespace(), crName)}
	}
}

// PodToCR 给 builder.Watches 用: 收到 Pod 变化 (尤其【删除】) → 返回要 reconcile 的 CR。
//
// 仅 Dynamo 用。动机 (会话确认): Dynamo 任务结束时 Pod 与 Workload 一起被删, 若某 Workload
// 删除事件到达时其 owner Pod 已先删, WorkloadToCR 会读不到 Pod → 反查不到 DGD → 漏触发
// "该标 Finished" 的 reconcile。而 Pod 删除事件里 Pod 对象【自带】label, 直接读即可, 不依赖
// 其它对象存活, 故 Pod watch 是 "全部 Pod 消失 → Finished" 的可靠触发源。
//
// 比 WorkloadToCR 更简单: Pod 直接带 dgd-name label, 无需走 owner 链 (少 1 跳)。
func PodToCR(crKind string) func(context.Context, client.Object) []reconcile.Request {
	labelKey := CRNameLabelFor(crKind)
	return func(ctx context.Context, obj client.Object) []reconcile.Request {
		if labelKey == "" {
			return nil
		}
		crName := obj.GetLabels()[labelKey]
		if crName == "" {
			return nil // 无关 Pod (无 dgd-name label)
		}
		return []reconcile.Request{req(obj.GetNamespace(), crName)}
	}
}

// ── 辅助 ──

// ownerOfKind 返回 obj 的 ownerReferences 中 kind==want 的第一个 (没有返 nil)。
func ownerOfKind(obj client.Object, want string) *ownerRef {
	for i := range obj.GetOwnerReferences() {
		if obj.GetOwnerReferences()[i].Kind == want {
			r := ownerRef{Name: obj.GetOwnerReferences()[i].Name}
			return &r
		}
	}
	return nil
}

type ownerRef struct{ Name string }

func req(namespace, name string) reconcile.Request {
	return reconcile.Request{NamespacedName: client.ObjectKey{Namespace: namespace, Name: name}}
}

// ── llm-d: 合成 key 映射 ──
//
// llmd 路的 reconcile key 不是对象名而是 platform.hyperpod.io/llmd-id (= DDB resource_id):
// LWS / gateway Deployment / gateway Pod 三种对象都带此 label (平台创建时不可变契约)。
// 好处: 零外部依赖 (不赌 <instance>-multi 命名约定), 三源事件按任务坍缩到同一 key
// (workqueue 自动合并), request.Name 即 resource_id。

// LlmdObjectToKey: LWS / gateway Deployment 事件 → 读自身 llmd-id label → key。
// delete 事件对象自带 label, 不依赖其它对象存活 (删除触发链可靠)。
// 无 label (手工 kubectl 建的, 如 llmd-b) → nil 天然过滤。
func LlmdObjectToKey() func(context.Context, client.Object) []reconcile.Request {
	return func(_ context.Context, obj client.Object) []reconcile.Request {
		id := obj.GetLabels()[gvk.LabelLlmdID]
		if id == "" {
			return nil
		}
		return []reconcile.Request{req(obj.GetNamespace(), id)}
	}
}

// LlmdWorkloadToKey: Workload 事件 → owner → llmd-id。两种 Workload 两个分支:
//   - LWS Workload: ownerRef 直含 LeaderWorkerSet (实证; v0.12.0 无任何 label 可读)
//     → cache 读 LWS → llmd-id
//   - gateway Workload: pod 级集成, ownerRef 是 Pod → cache 读 Pod → llmd-id
//
// owner 已先删读不到 → nil, 无害: owner 自己的删除事件必触发同 key 的 reconcile。
// 训练/推理/开发机的 Workload: owner 无 llmd-id → nil 过滤。
func LlmdWorkloadToKey(reader client.Reader) func(context.Context, client.Object) []reconcile.Request {
	return func(ctx context.Context, obj client.Object) []reconcile.Request {
		if ref := ownerOfKind(obj, "LeaderWorkerSet"); ref != nil {
			lws := gvk.NewUnstructured(gvk.LlmdLWS)
			key := client.ObjectKey{Namespace: obj.GetNamespace(), Name: ref.Name}
			if err := reader.Get(ctx, key, lws); err != nil {
				return nil
			}
			if id := lws.GetLabels()[gvk.LabelLlmdID]; id != "" {
				return []reconcile.Request{req(obj.GetNamespace(), id)}
			}
			return nil
		}
		if ref := ownerOfKind(obj, "Pod"); ref != nil {
			var pod corev1.Pod
			key := client.ObjectKey{Namespace: obj.GetNamespace(), Name: ref.Name}
			if err := reader.Get(ctx, key, &pod); err != nil {
				return nil
			}
			if id := pod.GetLabels()[gvk.LabelLlmdID]; id != "" {
				return []reconcile.Request{req(obj.GetNamespace(), id)}
			}
		}
		return nil
	}
}
