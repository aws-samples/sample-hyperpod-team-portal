"""DynamoGraphDeployment CR 适配器.

职责:
    DynamoGraphDeployment CR 的 create/get/delete/list.

对应 CR:
    nvidia.com/v1beta1
    kind: DynamoGraphDeployment
    plural: dynamographdeployments

实测 (2026-07-11 demo): 单机 frontend+worker / 多机 frontend+worker-ldr+worker-wkr,
走 Kueue pod integration (grove 给每 pod 打 kueue.x-k8s.io/managed), invoke frontend SVC:8000。
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


class DynamoMixin(K8sClientBase):
    """DynamoGraphDeployment CR CRUD."""

    _DYN_GROUP = "nvidia.com"
    _DYN_VERSION = "v1beta1"
    _DYN_PLURAL = "dynamographdeployments"

    # Grove PodCliqueSet (gang 编排顶层对象); 其 name = 该 DGD 所有 Pod 的名字前缀,
    # 其 label nvidia.com/dynamo-graph-deployment-name = 完整 DGD 名 (CR 名太长时 PCS
    # 名会被截断, 故必须靠 label 还原 DGD 名, 不能拿 PCS 名当 DGD 名)。用于任务总览
    # 排队顺序把 pending workload 的 owner Pod 名归一回 DGD (已实测确认)。
    _PCS_GROUP = "grove.io"
    _PCS_VERSION = "v1alpha1"
    _PCS_PLURAL = "podcliquesets"

    async def create_dynamo_deployment(
        self, namespace: str, cr: dict[str, Any]
    ) -> dict[str, Any]:
        """Create DynamoGraphDeployment CR."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._DYN_GROUP,
                    version=self._DYN_VERSION,
                    namespace=namespace,
                    plural=self._DYN_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_dynamo_deployment.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def get_dynamo_deployment(
        self, namespace: str, name: str
    ) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=self._DYN_GROUP,
                    version=self._DYN_VERSION,
                    namespace=namespace,
                    plural=self._DYN_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def list_dynamo_deployments(
        self, namespace: str
    ) -> list[dict[str, Any]]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.list_namespaced_custom_object(
                    group=self._DYN_GROUP,
                    version=self._DYN_VERSION,
                    namespace=namespace,
                    plural=self._DYN_PLURAL,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        items = resp.get("items", []) if isinstance(resp, dict) else []
        return [_to_primitive(it) if hasattr(it, "to_dict") else it for it in items]

    async def list_podcliquesets(self, namespace: str) -> list[dict[str, Any]]:
        """列 ns 内全部 Grove PodCliqueSet (每个 dynamo DGD 一个, 非 per-pod)。

        返回 dict 列表, 调用方读 metadata.name (= Pod 名前缀) + metadata.labels
        [nvidia.com/dynamo-graph-deployment-name] (= 完整 DGD 名) 建映射。
        PCS 不随 pending Pod 抖动重建 (比 list Pod 更稳、量更小)。
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.list_namespaced_custom_object(
                    group=self._PCS_GROUP,
                    version=self._PCS_VERSION,
                    namespace=namespace,
                    plural=self._PCS_PLURAL,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        items = resp.get("items", []) if isinstance(resp, dict) else []
        return [_to_primitive(it) if hasattr(it, "to_dict") else it for it in items]

    async def delete_dynamo_deployment(
        self, namespace: str, name: str
    ) -> None:
        """Delete DynamoGraphDeployment CR. 404 is idempotent (grove 级联回收 pod)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._DYN_GROUP,
                    version=self._DYN_VERSION,
                    namespace=namespace,
                    plural=self._DYN_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
