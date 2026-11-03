"""InferenceEndpointConfig CR 适配器.

职责:
    InferenceEndpointConfig CR 的 create/get/delete/list.

对应 CR:
    inference.sagemaker.aws.amazon.com/v1
    kind: InferenceEndpointConfig
    plural: inferenceendpointconfigs

官方 URL:
    https://docs.aws.amazon.com/sagemaker/latest/dg/inference-operator.html
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


class InferenceMixin(K8sClientBase):
    """InferenceEndpointConfig CR CRUD."""

    _IEC_GROUP = "inference.sagemaker.aws.amazon.com"
    _IEC_VERSION = "v1"
    _IEC_PLURAL = "inferenceendpointconfigs"

    async def create_inference_endpoint(
        self, namespace: str, cr: dict[str, Any]
    ) -> dict[str, Any]:
        """Create InferenceEndpointConfig CR."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._IEC_GROUP,
                    version=self._IEC_VERSION,
                    namespace=namespace,
                    plural=self._IEC_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_inference_endpoint.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def get_inference_endpoint(
        self, namespace: str, name: str
    ) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=self._IEC_GROUP,
                    version=self._IEC_VERSION,
                    namespace=namespace,
                    plural=self._IEC_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    # 读 ALB DNS 已提到 IngressMixin.get_alb_dns (llm-d 也要用)

    async def list_inference_endpoints(
        self, namespace: str
    ) -> list[dict[str, Any]]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.list_namespaced_custom_object(
                    group=self._IEC_GROUP,
                    version=self._IEC_VERSION,
                    namespace=namespace,
                    plural=self._IEC_PLURAL,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        items = resp.get("items", []) if isinstance(resp, dict) else []
        return [_to_primitive(it) if hasattr(it, "to_dict") else it for it in items]

    async def delete_inference_endpoint(
        self, namespace: str, name: str
    ) -> None:
        """Delete InferenceEndpointConfig CR. 404 is idempotent."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._IEC_GROUP,
                    version=self._IEC_VERSION,
                    namespace=namespace,
                    plural=self._IEC_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
