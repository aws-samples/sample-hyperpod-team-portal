"""Workspace CR 适配器.

职责:
    Workspace CR (SageMaker Spaces 包装) 的 CRUD.

对应 CR:
    workspace.jupyter.org/v1alpha1 · kind: Workspace · plural: workspaces

官方 URL:
    https://docs.aws.amazon.com/sagemaker/latest/dg/studio-spaces.html
    https://jupyter.org/enhancement-proposals/ (workspace operator)
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


class WorkspaceMixin(K8sClientBase):
    """Workspace CR CRUD."""

    _WS_GROUP = "workspace.jupyter.org"
    _WS_VERSION = "v1alpha1"
    _WS_PLURAL = "workspaces"

    async def create_workspace(
        self, namespace: str, cr: dict[str, Any]
    ) -> dict[str, Any]:
        """创建 Workspace CR."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_workspace.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def get_workspace(
        self, namespace: str, name: str
    ) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def list_workspaces(
        self,
        namespace: str | None = None,
        label_selector: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                if namespace:
                    resp = await co.list_namespaced_custom_object(
                        group=self._WS_GROUP,
                        version=self._WS_VERSION,
                        namespace=namespace,
                        plural=self._WS_PLURAL,
                        label_selector=label_selector or "",
                    )
                else:
                    resp = await co.list_cluster_custom_object(
                        group=self._WS_GROUP,
                        version=self._WS_VERSION,
                        plural=self._WS_PLURAL,
                        label_selector=label_selector or "",
                    )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        return list(data.get("items", []))

    async def patch_workspace(
        self, namespace: str, name: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge patch spec (用 application/merge-patch+json)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                # kubernetes-asyncio 默认 strategic merge 对 CR 无效, 用 merge-patch
                resp = await co.patch_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_PLURAL,
                    name=name,
                    body=patch,
                    _content_type="application/merge-patch+json",
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def delete_workspace(self, namespace: str, name: str) -> None:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                return  # 已被删, 幂等
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
