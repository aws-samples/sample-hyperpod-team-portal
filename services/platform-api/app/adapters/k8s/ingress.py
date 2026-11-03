"""Ingress 适配器.

职责:
    读 Ingress 的 ALB DNS (供各推理管道回填 endpoint_url)。

对应 K8s 资源:
    networking.k8s.io/v1 Ingress (内建资源, 非 CR)

命名约定: 各管道的 Ingress 统一叫 ``alb-<资源名>``, 故读取逻辑共用。
"""

from __future__ import annotations

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from .base import K8sClientBase
from .errors import K8sAPIError


class IngressMixin(K8sClientBase):
    """networking.k8s.io/v1 Ingress 读取."""

    async def get_alb_dns(self, namespace: str, name: str) -> str | None:
        """读 ingress ``alb-<name>`` 的 ALB DNS; 无 ingress 或未分配地址返 None。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                net = k8s_client.NetworkingV1Api(api)
                ing = await net.read_namespaced_ingress(
                    name=f"alb-{name}", namespace=namespace
                )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        lb = (
            (ing.status.load_balancer.ingress or [])
            if ing.status and ing.status.load_balancer
            else []
        )
        return lb[0].hostname if lb else None
