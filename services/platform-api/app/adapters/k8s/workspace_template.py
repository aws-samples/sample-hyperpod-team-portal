"""WorkspaceTemplate CR 适配器.

职责:
    WorkspaceTemplate CR 的 CRUD · 管理员侧用于管理可选镜像 / 默认资源等.

对应 CR:
    workspace.jupyter.org/v1alpha1 · kind: WorkspaceTemplate · plural: workspacetemplates

官方 URL:
    https://docs.aws.amazon.com/sagemaker/latest/dg/studio-spaces-customization.html
    (Example custom JupyterLab/Code Editor template 字段定义)
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


class WorkspaceTemplateMixin(K8sClientBase):
    """WorkspaceTemplate CR CRUD."""

    _WS_GROUP = "workspace.jupyter.org"
    _WS_VERSION = "v1alpha1"
    _WS_TEMPLATE_PLURAL = "workspacetemplates"

    async def get_workspace_template(
        self, name: str, namespace: str = "jupyter-k8s-system"
    ) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_TEMPLATE_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def list_workspace_templates(
        self, namespace: str = "jupyter-k8s-system"
    ) -> list[dict[str, Any]]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.list_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_TEMPLATE_PLURAL,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        return list(data.get("items", []))

    async def create_workspace_template(
        self, cr: dict[str, Any], namespace: str = "jupyter-k8s-system"
    ) -> dict[str, Any]:
        """管理员创建自定义 WorkspaceTemplate.

        严格对齐官方 customization.html 'Example custom JupyterLab/Code Editor
        template' 的字段集:
          spec.displayName / description / defaultImage / allowedImages[]
          / defaultResources / primaryStorage / defaultContainerConfig
          / defaultPodSecurityContext / defaultOwnershipType
          / defaultAccessStrategy / allowSecondaryStorages / appType
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_TEMPLATE_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_workspace_template.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def patch_workspace_template(
        self,
        name: str,
        patch: dict[str, Any],
        namespace: str = "jupyter-k8s-system",
    ) -> dict[str, Any]:
        """merge-patch 自定义 WorkspaceTemplate (例如追加 allowedImages)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.patch_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_TEMPLATE_PLURAL,
                    name=name,
                    body=patch,
                    _content_type="application/merge-patch+json",
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def delete_workspace_template(
        self, name: str, namespace: str = "jupyter-k8s-system"
    ) -> None:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._WS_GROUP,
                    version=self._WS_VERSION,
                    namespace=namespace,
                    plural=self._WS_TEMPLATE_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
