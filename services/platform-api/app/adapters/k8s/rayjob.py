"""RayJob CR 适配器.

职责:
    RayJob CR 的 create/get/delete.

对应 CR:
    ray.io/v1
    kind: RayJob
    plural: rayjobs

实测 (2026-07-18~20 demo): HTTPMode 提交 (不建 submitter Job), head+worker 组 Ray
集群, GPU+FSx 端到端 SUCCEEDED。pod label ray.io/cluster=<clustername> 反查 pod。
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


class RayJobMixin(K8sClientBase):
    """RayJob CR CRUD."""

    _RAY_GROUP = "ray.io"
    _RAY_VERSION = "v1"
    _RAY_PLURAL = "rayjobs"

    async def create_rayjob(
        self, namespace: str, cr: dict[str, Any]
    ) -> dict[str, Any]:
        """Create RayJob CR."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._RAY_GROUP,
                    version=self._RAY_VERSION,
                    namespace=namespace,
                    plural=self._RAY_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_rayjob.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def get_rayjob(self, namespace: str, name: str) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=self._RAY_GROUP,
                    version=self._RAY_VERSION,
                    namespace=namespace,
                    plural=self._RAY_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def delete_rayjob(self, namespace: str, name: str) -> None:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._RAY_GROUP,
                    version=self._RAY_VERSION,
                    namespace=namespace,
                    plural=self._RAY_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
