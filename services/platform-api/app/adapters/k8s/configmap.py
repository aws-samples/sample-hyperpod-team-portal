"""ConfigMap 适配器.

职责:
    平台管理的 per-CR ConfigMap 增删 (当前用于 Dynamo OTel sidecar 抓取配置)。

对应 K8s 资源:
    core/v1 ConfigMap (内建资源, 非 CR)

背景: IEC 的 OTel configmap 由 IEC operator 自动建; dynamo-operator/grove 不管监控,
故 Dynamo 的 OTel configmap 要平台自己建 (随 CR 生命周期: create 建 / delete 删)。
"""

from __future__ import annotations

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase
from .errors import K8sAPIError

logger = get_logger(__name__)


class ConfigMapMixin(K8sClientBase):
    """core/v1 ConfigMap 增删 (平台管理的 per-CR configmap)."""

    async def apply_config_map(
        self, namespace: str, name: str, data: dict[str, str]
    ) -> None:
        """创建或覆盖 ConfigMap (存在则 replace, 幂等)."""
        body = k8s_client.V1ConfigMap(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            data=data,
        )
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                try:
                    await v1.create_namespaced_config_map(namespace, body)
                except ApiException as exc:
                    if exc.status == 409:
                        # 已存在 → replace (克隆/重建同名场景幂等)
                        await v1.replace_namespaced_config_map(name, namespace, body)
                    else:
                        raise
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def delete_config_map(self, namespace: str, name: str) -> None:
        """删 ConfigMap. 404 幂等 (已删/未建)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                await v1.delete_namespaced_config_map(name, namespace)
        except ApiException as exc:
            if exc.status == 404:
                return
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
