"""HyperPodPyTorchJob CR 适配器.

职责:
    HyperPodPyTorchJob CR 的 create/get/delete.

对应 CR:
    sagemaker.amazonaws.com/v1 · kind: HyperPodPyTorchJob · plural: hyperpodpytorchjobs

官方 URL:
    https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod-eks-operator.html
    https://github.com/aws/sagemaker-hyperpod-training-operator
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


class HpjMixin(K8sClientBase):
    """HyperPodPyTorchJob CR CRUD."""

    _HPJ_GROUP = "sagemaker.amazonaws.com"
    _HPJ_VERSION = "v1"
    _HPJ_PLURAL = "hyperpodpytorchjobs"

    async def create_hyperpod_pytorch_job(
        self, namespace: str, cr: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a HyperPodPyTorchJob CR (sagemaker.amazonaws.com/v1)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.create_namespaced_custom_object(
                    group=self._HPJ_GROUP,
                    version=self._HPJ_VERSION,
                    namespace=namespace,
                    plural=self._HPJ_PLURAL,
                    body=cr,
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_hp_pytorch_job.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def get_hyperpod_pytorch_job(
        self, namespace: str, name: str
    ) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_namespaced_custom_object(
                    group=self._HPJ_GROUP,
                    version=self._HPJ_VERSION,
                    namespace=namespace,
                    plural=self._HPJ_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def delete_hyperpod_pytorch_job(
        self, namespace: str, name: str
    ) -> None:
        """Delete a HyperPodPyTorchJob CR. 404 is idempotent."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                await co.delete_namespaced_custom_object(
                    group=self._HPJ_GROUP,
                    version=self._HPJ_VERSION,
                    namespace=namespace,
                    plural=self._HPJ_PLURAL,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
