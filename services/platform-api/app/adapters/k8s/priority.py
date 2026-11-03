"""Kueue 优先级相关 K8s 适配器 (Workload + ClusterQueue).

纯 K8s 代理, 不落 DDB。

WorkloadPriorityClass (WPC) 操作已迁到 SageMaker scheduler config
(见 adapters/aws/scheduler_config.py); 本 adapter 只保留 Workload / ClusterQueue 操作。

对应资源 (kueue.x-k8s.io/v1beta1):
    - Workload               (ns 级)   任务的 Kueue 工作负载, 带 .spec.priority 快照
    - ClusterQueue           (集群级)  队列 + 抢占开关 (.spec.preemption.withinClusterQueue)

实测 (2026-06-11): Workload.spec.priority 可 patch (pending 也行);
SageMaker 托管 ClusterQueue patch withinClusterQueue 不被 reconcile 打回。
"""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase, _to_primitive
from .errors import K8sAPIError

logger = get_logger(__name__)

_MERGE_PATCH = "application/merge-patch+json"


class PriorityMixin(K8sClientBase):
    """Workload / ClusterQueue 操作 (Kueue). WPC 已迁到 SageMaker scheduler config。"""

    _KUEUE_GROUP = "kueue.x-k8s.io"
    _KUEUE_VERSION = "v1beta1"
    _WORKLOAD_PLURAL = "workloads"
    _CQ_PLURAL = "clusterqueues"
    _VISIBILITY_GROUP = "visibility.kueue.x-k8s.io"
    _VISIBILITY_VERSION = "v1beta1"

    # ---------- Workload (ns 级, 任务的 Kueue 工作负载) ----------

    async def list_workloads(self, namespace: str) -> list[dict[str, Any]]:
        """列某 ns 的 Kueue Workload (带 spec.priority + ownerReferences + 状态)。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.list_namespaced_custom_object(
                    group=self._KUEUE_GROUP,
                    version=self._KUEUE_VERSION,
                    namespace=namespace,
                    plural=self._WORKLOAD_PLURAL,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        return list(data.get("items", []))

    async def find_workload_by_owner(
        self, namespace: str, cr_name: str
    ) -> dict[str, Any] | None:
        """按任务 CR name 反查对应 Workload (匹配 ownerReferences[].name)。

        任务总览页有 CR name (如 ddp-bob-queue-b424ec), Workload 名带 hash, 靠 ownerRef 关联。
        """
        for wl in await self.list_workloads(namespace):
            owners = (wl.get("metadata") or {}).get("ownerReferences") or []
            if any(o.get("name") == cr_name for o in owners):
                return wl
        return None

    # cr_name → "Kueue job 对象" 的 Pod 关联 label (开发机/推理 Workload owned by Pod)。
    # 真集群实证 (2026-06-11): Workload.label[job-uid] == 它直接 owner 的 uid。
    #   训练: owner = CR 自己          → 直接 get CR 拿 uid (不在此表)
    #   开发机: owner = Pod, Pod 靠 workspace.jupyter.org/workspace-name == cr_name 找
    #   推理:  owner = Pod, Pod 靠 app == cr_name 找
    _POD_NAME_LABEL = {
        "dev": "workspace.jupyter.org/workspace-name",
        "inference": "app",
    }
    _JOB_UID_LABEL = "kueue.x-k8s.io/job-uid"

    async def _job_uid_for_task(
        self, namespace: str, task_type: str, cr_name: str
    ) -> str | None:
        """拿到 Workload.label[job-uid] 对应的 uid。

        训练: HyperPodPyTorchJob CR 自己的 uid。
        开发机/推理: 业务 Pod 的 uid (Kueue 为 Pod 建 Workload)。
        """
        if task_type in ("train", "rayjob"):
            group, version, plural = self._TASK_CR_COORDS[task_type]
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                cr = await co.get_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                    name=cr_name,
                )
            cr = _to_primitive(cr) if hasattr(cr, "to_dict") else cr
            return (cr.get("metadata") or {}).get("uid")

        pod_label = self._POD_NAME_LABEL.get(task_type)
        if pod_label is None:
            raise K8sAPIError("BadType", f"unknown task type: {task_type}")
        async with ApiClient() as api:
            core = k8s_client.CoreV1Api(api)
            resp = await core.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"{pod_label}={cr_name}",
            )
        items = getattr(resp, "items", None) or []
        if not items:
            return None
        return items[0].metadata.uid

    async def find_workload_for_task(
        self, namespace: str, task_type: str, cr_name: str
    ) -> dict[str, Any] | None:
        """三类通用反查 Workload (按 type 拿 job-uid → label_selector 精确查, 不遍历)。

        替代 find_workload_by_owner (后者 owner.name 精确匹配只对训练成立)。
        task_type 由前端 TaskRow.kind 提供 (dev/train/inference)。
        """
        await self._load_config()
        uid = await self._job_uid_for_task(namespace, task_type, cr_name)
        if not uid:
            return None
        async with ApiClient() as api:
            co = k8s_client.CustomObjectsApi(api)
            resp = await co.list_namespaced_custom_object(
                group=self._KUEUE_GROUP,
                version=self._KUEUE_VERSION,
                namespace=namespace,
                plural=self._WORKLOAD_PLURAL,
                label_selector=f"{self._JOB_UID_LABEL}={uid}",
            )
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        items = data.get("items") or []
        return items[0] if items else None

    # 任务 CR 坐标 (按 type 改 priority-class label 用)。实测: Workload.spec.priority
    # 被 Kueue webhook 锁死 (priorityClassSource=workloadpriorityclass), 直接 patch
    # Workload 不生效 → 改单任务优先级须改源 CR 的 label, 再删 Workload 让 Kueue 重建。
    _TASK_CR_COORDS = {
        "train": ("sagemaker.amazonaws.com", "v1", "hyperpodpytorchjobs"),
        "inference": (
            "inference.sagemaker.aws.amazon.com",
            "v1",
            "inferenceendpointconfigs",
        ),
        "dev": ("workspace.jupyter.org", "v1alpha1", "workspaces"),
        "rayjob": ("ray.io", "v1", "rayjobs"),
    }
    _PRIORITY_LABEL = "kueue.x-k8s.io/priority-class"

    async def patch_task_priority_label(
        self,
        task_type: str,
        namespace: str,
        cr_name: str,
        priority_class_name: str,
    ) -> None:
        """改任务 CR 的 priority-class label (按 type 定位 CR 坐标)。

        改完需配合 delete_workload 让 Kueue 按新 label 重建 Workload (新 priority 生效)。
        """
        coord = self._TASK_CR_COORDS.get(task_type)
        if coord is None:
            raise K8sAPIError("BadType", f"unknown task type: {task_type}")
        group, version, plural = coord
        patch = {
            "metadata": {"labels": {self._PRIORITY_LABEL: priority_class_name}}
        }
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.patch_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                    name=cr_name,
                    body=patch,
                    _content_type=_MERGE_PATCH,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def delete_workload(self, namespace: str, workload_name: str) -> None:
        """删 Kueue Workload (Kueue 会按源 CR 当前 label 自动重建 → 新 priority 生效)。

        pending: 重新排队 (安全); running: Kueue 重新走准入 (可能短暂重调度,
        HyperPod auto-resume 接住)。改单任务优先级靠 改 label + 删 Workload 组合。
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._KUEUE_GROUP,
                    version=self._KUEUE_VERSION,
                    namespace=namespace,
                    plural=self._WORKLOAD_PLURAL,
                    name=workload_name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def delete_deployment(self, namespace: str, name: str) -> None:
        """删 Deployment (开发机/推理改优先级用)。

        开发机/推理 Workload owned by Pod, Pod 的 priority-class label 来自
        Deployment template (operator 创建时按 Workspace CR 当时 label 写入, 之后
        改 CR label 不会同步到已存 Deployment)。实测 (2026-06-11): 改 CR label + 删
        Deployment → operator 按 CR 当前 label 重建 Deployment → 新 Pod 带新 label →
        Kueue 按新 label 建 Workload → 新优先级生效。
        ⚠️ 删 Deployment = 重启用户的开发机/推理容器 (会话中断)。
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                apps = k8s_client.AppsV1Api(api)
                await apps.delete_namespaced_deployment(
                    name=name, namespace=namespace
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def list_pending_workloads(
        self, namespace: str, localqueue: str
    ) -> list[dict[str, Any]]:
        """列某 LocalQueue 的待调度 Workload (Kueue visibility 扩展 API)。

        返回 items, 每项含 metadata.ownerReferences[].name + positionInLocalQueue。
        visibility 是扩展 API server (非普通 CRD), 标准 CustomObjectsApi 不支持其
        自定义 subresource (pendingworkloads), 故用底层 call_api 发 raw GET。
        """
        path = (
            f"/apis/{self._VISIBILITY_GROUP}/{self._VISIBILITY_VERSION}"
            f"/namespaces/{namespace}/localqueues/{localqueue}/pendingworkloads"
        )
        try:
            await self._load_config()
            async with ApiClient() as api:
                resp = await api.call_api(
                    path,
                    "GET",
                    response_types_map={200: "object"},
                    auth_settings=["BearerToken"],
                    _return_http_data_only=True,
                    _preload_content=True,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        return list((data or {}).get("items", []))

    # ---------- ClusterQueue (集群级, 抢占开关) ----------

    async def get_clusterqueue(self, name: str) -> dict[str, Any]:
        """读 ClusterQueue (取 preemption.withinClusterQueue)。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_cluster_custom_object(
                    group=self._KUEUE_GROUP,
                    version=self._KUEUE_VERSION,
                    plural=self._CQ_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def patch_clusterqueue_preemption(
        self, name: str, within_cluster_queue: str
    ) -> dict[str, Any]:
        """patch ClusterQueue 的 preemption.withinClusterQueue (Never|LowerPriority)。

        实测 SageMaker 托管的 ClusterQueue patch 不被 reconcile 打回。开抢占 = LowerPriority。
        """
        patch = {
            "spec": {"preemption": {"withinClusterQueue": within_cluster_queue}}
        }
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.patch_cluster_custom_object(
                    group=self._KUEUE_GROUP,
                    version=self._KUEUE_VERSION,
                    plural=self._CQ_PLURAL,
                    name=name,
                    body=patch,
                    _content_type=_MERGE_PATCH,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp
