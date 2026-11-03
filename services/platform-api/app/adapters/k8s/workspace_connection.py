"""WorkspaceConnection 适配器 (aggregated API).

职责:
    POST 一次性 WorkspaceConnection CR, 换取 VSCode Remote URL.
    aggregated API server (jupyter-k8s-system/extension-server) 不持久化对象,
    每次用都要重新 create.

对应 CR:
    connection.workspace.jupyter.org/v1alpha1 · kind: WorkspaceConnection
    plural: workspaceconnections

官方 URL:
    https://docs.aws.amazon.com/sagemaker/latest/dg/vscode-access.html
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


class WorkspaceConnectionMixin(K8sClientBase):
    """WorkspaceConnection aggregated API 封装 (POST-only)."""

    # SageMaker Spaces Remote Access (aggregated API, POST-only)
    # Ref: https://docs.aws.amazon.com/sagemaker/latest/dg/vscode-access.html
    # server 端:jupyter-k8s-system/extension-server · 仅支持 create (不持久化)
    _CONN_GROUP = "connection.workspace.jupyter.org"
    _CONN_VERSION = "v1alpha1"
    _CONN_PLURAL = "workspaceconnections"

    async def create_workspace_connection(
        self,
        namespace: str,
        workspace_name: str,
        connection_type: str = "vscode-remote",
    ) -> dict[str, Any]:
        """Create a WorkspaceConnection · 一次性换 VSCode Remote URL.

        官方 aggregated API (extension-server in jupyter-k8s-system) 不持久化
        对象, 只在 POST 响应体 status.workspaceConnectionUrl 返 URL.
        URL 内含 SSM data-channel sessionToken, 有效期短, 每次用都要重新 create.

        Ref: https://docs.aws.amazon.com/sagemaker/latest/dg/vscode-access.html
        """
        cr = {
            "apiVersion": f"{self._CONN_GROUP}/{self._CONN_VERSION}",
            "kind": "WorkspaceConnection",
            "metadata": {
                # aggregated API 忽略 name (不持久化), 但 k8s client 要求给个值
                "generateName": f"{workspace_name}-conn-",
                "namespace": namespace,
            },
            "spec": {
                "workspaceName": workspace_name,
                "workspaceConnectionType": connection_type,
            },
        }
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._CONN_GROUP,
                    version=self._CONN_VERSION,
                    namespace=namespace,
                    plural=self._CONN_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_workspace_connection.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp
