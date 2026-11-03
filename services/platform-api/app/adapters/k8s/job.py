"""batch/v1 Job 适配器.

职责:
    batch/v1 Job 的 create/get/delete + 按 job-name 列 Pod.

对应 K8s 资源:
    batch/v1 Job (内建资源, 非 CR)
    常用于旧版训练任务编排 (HyperPodPyTorchJob 之前的过渡方案).

官方 URL:
    https://kubernetes.io/docs/concepts/workloads/controllers/job/
"""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase
from .errors import K8sAPIError

logger = get_logger(__name__)


class JobMixin(K8sClientBase):
    """batch/v1 Job CRUD + 关联 Pod 查询."""

    async def create_job(
        self, namespace: str, job: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a batch/v1 Job. Body is a plain dict matching the k8s schema."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                batch = k8s_client.BatchV1Api(api)
                resp = await batch.create_namespaced_job(
                    namespace=namespace, body=job
                )
        except ApiException as exc:
            logger.warning(
                "k8s.create_job.api_error",
                status=exc.status,
                reason=exc.reason,
                body=getattr(exc, "body", None),
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}",
                f"{exc.reason}: {getattr(exc, 'body', '')}",
            ) from exc
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    async def get_job(self, namespace: str, name: str) -> dict[str, Any]:
        try:
            await self._load_config()
            async with ApiClient() as api:
                batch = k8s_client.BatchV1Api(api)
                resp = await batch.read_namespaced_job(
                    name=name, namespace=namespace
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return resp.to_dict() if hasattr(resp, "to_dict") else resp

    async def delete_job(
        self, namespace: str, name: str, *, propagation: str = "Background"
    ) -> None:
        """Delete a Job. Propagation=Background also reaps owned Pods."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                batch = k8s_client.BatchV1Api(api)
                await batch.delete_namespaced_job(
                    name=name,
                    namespace=namespace,
                    propagation_policy=propagation,
                )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc

    async def list_pods_by_job(
        self, namespace: str, job_name: str
    ) -> list[dict[str, Any]]:
        """List pods owned by a Job via its controller-uid / job-name label."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                core = k8s_client.CoreV1Api(api)
                resp = await core.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"job-name={job_name}",
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        items = resp.items or []
        return [p.to_dict() if hasattr(p, "to_dict") else p for p in items]
