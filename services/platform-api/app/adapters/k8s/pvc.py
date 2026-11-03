"""PVC 列表适配器.

职责:
    给前端挑共享存储用, 默认只返 Bound 状态 PVC.

对应 K8s 资源:
    core/v1 PersistentVolumeClaim (内建资源, 非 CR)

官方 URL:
    https://kubernetes.io/docs/concepts/storage/persistent-volumes/
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


class PvcMixin(K8sClientBase):
    """core/v1 PersistentVolumeClaim 只读操作."""

    async def list_pvcs(
        self, namespace: str, phase_filter: str | None = "Bound"
    ) -> list[dict[str, Any]]:
        """列 namespace 下 PVC. 默认只返 Bound 的 (可挂)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.list_namespaced_persistent_volume_claim(
                    namespace=namespace
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        items = data.get("items", []) or []
        if phase_filter:
            items = [
                p
                for p in items
                if ((p.get("status") or {}).get("phase")) == phase_filter
            ]
        return items

    async def pvc_exists(
        self, namespace: str, name: str, *, require_bound: bool = False
    ) -> bool:
        """查单个 PVC 是否存在 (require_bound=True 时还要求 phase==Bound).

        用于 attach 回读校验 + 开发机创建前校验挂载真实可用.
        NotFound → False; 其他 API 错抛 K8sAPIError.
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.read_namespaced_persistent_volume_claim(
                    name=name, namespace=namespace
                )
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        if not require_bound:
            return True
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        return ((data.get("status") or {}).get("phase")) == "Bound"
