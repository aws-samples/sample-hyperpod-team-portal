// Package gvk 集中定义本 controller 监听的所有 K8s 资源坐标 (GroupVersionKind)。
//
// 单一真相源: 各类业务 CR + Kueue Workload + Pod。坐标取自现有 Python informer
// (services/platform-worker/worker/informers/*.py) 与 adapters/k8s/workload.py,
// 已交叉核实。这些都是外部 CRD/内建资源, 本仓库无 typed Go struct, 故统一用
// unstructured.Unstructured + 显式 GVK 处理 (controller-runtime 对无 typed API
// 的标准做法)。
package gvk

import (
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// ── 业务 CR ──
var (
	// Training: HyperPodPyTorchJob (sagemaker.amazonaws.com/v1)
	Training = schema.GroupVersionKind{
		Group:   "sagemaker.amazonaws.com",
		Version: "v1",
		Kind:    "HyperPodPyTorchJob",
	}
	// Inference: InferenceEndpointConfig (inference.sagemaker.aws.amazon.com/v1)
	Inference = schema.GroupVersionKind{
		Group:   "inference.sagemaker.aws.amazon.com",
		Version: "v1",
		Kind:    "InferenceEndpointConfig",
	}
	// DevInstance: Workspace (workspace.jupyter.org/v1alpha1)
	DevInstance = schema.GroupVersionKind{
		Group:   "workspace.jupyter.org",
		Version: "v1alpha1",
		Kind:    "Workspace",
	}
	// DynamoGraph: DynamoGraphDeployment (nvidia.com/v1beta1) — NVIDIA Dynamo 多机推理。
	// 一个 DGD 对应多个 Pod → 多个 Kueue Workload (owner=Pod, 每 Pod 一个 Workload);
	// 反查/关联同推理/开发机走 2 跳 (Workload→Pod→DGD, 经 Pod label)。实测确认坐标。
	DynamoGraph = schema.GroupVersionKind{
		Group:   "nvidia.com",
		Version: "v1beta1",
		Kind:    "DynamoGraphDeployment",
	}

	// RayJob: RayJob (ray.io/v1) — KubeRay 的 Ray 训练/批处理任务。
	// Kueue Workload 通过 ownerRef 直指 RayJob CR (controller=true, 1:1 单跳),
	// 关联形态同训练 (job-uid = CR.uid), 故走 watchOwns。实测确认坐标。
	RayJob = schema.GroupVersionKind{
		Group:   "ray.io",
		Version: "v1",
		Kind:    "RayJob",
	}

	// RayCluster: RayCluster (ray.io/v1) — KubeRay 为每个 RayJob 派生的集群对象,
	// 是 head+worker Pod 的 owner (ownerRef controller=true)。ttl 到期时 KubeRay 只删
	// RayCluster (级联删 Pod), 而 RayJob CR + Workload 永久留存 (已实测确认)。
	// 故 RayCluster 是否存在 = 该 Ray 任务此刻是否还占 GPU 的唯一可靠信号。
	// RayCluster.ownerRef 直指 RayJob (controller=true) → builder.Owns 1 跳自动映射。
	RayCluster = schema.GroupVersionKind{
		Group:   "ray.io",
		Version: "v1",
		Kind:    "RayCluster",
	}

	// LlmdLWS: LeaderWorkerSet (leaderworkerset.x-k8s.io/v1) — llm-d 多机推理的工作负载单位。
	// 1 个 LWS (replicas=N) = N 个 Kueue Workload (每 replica group 一个, ownerRef 含 LWS+组内 Pod,
	// v0.12.0 无任何 label → 关联走 ownerRef 过滤, 已实测确认)。
	LlmdLWS = schema.GroupVersionKind{
		Group:   "leaderworkerset.x-k8s.io",
		Version: "v1",
		Kind:    "LeaderWorkerSet",
	}

	// Deployment (apps/v1) — llm-d 的 gateway (sgl-model-gateway, 服务入口)。
	// 与 LWS 平级顶层资源 (无 ownerRef 级联), 平台分开创建/删除。
	// informer 挂 llmd-id Exists selector (main.go), 只缓存 llm-d 的 gateway。
	Deployment = schema.GroupVersionKind{
		Group:   "apps",
		Version: "v1",
		Kind:    "Deployment",
	}

	// Kueue Workload (kueue.x-k8s.io/v1beta1) — 派生 kueue_status 的来源
	Workload = schema.GroupVersionKind{
		Group:   "kueue.x-k8s.io",
		Version: "v1beta1",
		Kind:    "Workload",
	}

	// Pod (core/v1) — 推理/开发机 2 跳 owner 链的中间节点
	Pod = schema.GroupVersionKind{
		Group:   "",
		Version: "v1",
		Kind:    "Pod",
	}
)

// AllCRs 是各种业务 CR 的坐标 (controller 各起一个 reconciler 监听)。
var AllCRs = []schema.GroupVersionKind{Training, Inference, DevInstance, DynamoGraph, RayJob}

// NewUnstructured 按 GVK 造一个空的 unstructured 对象 (供 builder.For/Watches +
// cache.Get 使用; controller-runtime 用它的 GVK 决定 watch 哪种资源)。
func NewUnstructured(g schema.GroupVersionKind) *unstructured.Unstructured {
	u := &unstructured.Unstructured{}
	u.SetGroupVersionKind(g)
	return u
}

// Kueue Workload 上标识其关联 job (训练=CR uid, 推理/开发机=Pod uid) 的 label key。
// 取自 adapters/k8s/workload.py。
const LabelJobUID = "kueue.x-k8s.io/job-uid"

// LabelTrainingPodCRName: 训练 Pod 上标识所属 CR name 的 label (实测确认 HPJob=<crname>)。
// 双重用途: (1) derive 训练 occupying 按此 label 查 Pod;
//
//	(2) cache 用 !HPJob (DoesNotExist) 把训练 Pod 挡在 cache 外
//	    (训练 Pod 上百且抖动, 不进 cache; 推理/开发机 Pod 无此 label, 正常缓存)。
const LabelTrainingPodCRName = "HPJob"

// LabelDynamoGraphName: Dynamo Pod 上标识所属 DGD name 的 label (实测确认,
// operator 从 DGD 透传到每个子 Pod, 三个 Pod 均带 =<DGD name>)。
// 用于 2 跳关联 (Workload→owner Pod→读此 label=DGD name) 与按 DGD 聚合其全部 Pod/Workload。
const LabelDynamoGraphName = "nvidia.com/dynamo-graph-deployment-name"

// LabelLlmdID: llm-d 任务的三种对象 (LWS / gateway Deployment / gateway Pod) 都带的
// 平台任务 ID label (= DDB resource_id, 实证三对象齐全)。它是 llmd 路 reconcile 的
// 合成 key: 事件映射读它入队, Reconcile 按它 List 双资源。创建时不可变 (与平台 API 约定)。
const LabelLlmdID = "platform.hyperpod.io/llmd-id"

// LabelLlmdWorkspaceID: llmd 对象上的 workspace-id label (DDB PK 来源)。
const LabelLlmdWorkspaceID = "platform.hyperpod.io/workspace-id"

// LabelRayOriginatedFromCRName: KubeRay 在 RayCluster 上打的、指回源 RayJob CR name 的
// label (实测 ray.io/originated-from-cr-name=<RayJob名>, bob-ray-12)。reconciler 按此
// label 从 cache List 该 RayJob 的 RayCluster —— RayCluster 名带随机后缀 (≠ CR 名),
// 不能按名 Get。
const LabelRayOriginatedFromCRName = "ray.io/originated-from-cr-name"
