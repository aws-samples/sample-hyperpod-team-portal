"""adapters/k8s · Kueue Workload 只读 (kueue.x-k8s.io/v1beta1)。"""
from __future__ import annotations

from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from .base import K8sClientBase
from .errors import K8sAPIError

_GROUP = "kueue.x-k8s.io"
_VERSION = "v1beta1"
_PLURAL = "workloads"


class WorkloadMixin(K8sClientBase):
    async def list_workloads_by_job_uid(
        self, namespace: str, job_uid: str
    ) -> list[dict[str, Any]]:
        """按 kueue.x-k8s.io/job-uid label 列 Workload。返回 dict 列表 (含 status.conditions)。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.list_namespaced_custom_object(
                    _GROUP, _VERSION, namespace, _PLURAL,
                    label_selector=f"kueue.x-k8s.io/job-uid={job_uid}",
                )
        except ApiException as exc:
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return resp.get("items") or []
