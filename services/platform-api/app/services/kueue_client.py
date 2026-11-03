"""Kueue ClusterQueue 只读客户端.

Scope:
- 只读 ClusterQueue CR 的 status (flavorsUsage / flavorsReservation / pendingWorkloads / admittedWorkloads)
- 不做 create/delete/patch
- 不 watch

使用方式:
    client = KueueClient(context="hypd-dev-cluster")
    status = await client.get_cluster_queue_status("hyperpod-ns-team-a-nlp-clusterqueue")
"""

from __future__ import annotations

from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import config as k8s_config
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger
from app.services.k8s_client import K8sAPIError, _to_primitive

logger = get_logger(__name__)


class KueueClient:
    """Kueue kueue.x-k8s.io/v1beta1 客户端 (read-only ClusterQueue)."""

    _GROUP = "kueue.x-k8s.io"
    _VERSION = "v1beta1"
    _PLURAL = "clusterqueues"

    def __init__(self, context: str | None = None) -> None:
        # context=None → kubeconfig current-context (跟 K8sClientBase 一致).
        # 调用方统一传 settings.kube_context 覆盖 (跨集群指向业务集群).
        self._context = context or None

    async def _load_config(self) -> None:
        if self._context:
            await k8s_config.load_kube_config(context=self._context)
        else:
            await k8s_config.load_kube_config()

    async def get_cluster_queue_status(self, name: str) -> dict[str, Any] | None:
        """读 ClusterQueue CR, 返 .status dict.

        - 不存在 (404): 返 None (调用方可据此回空结果)
        - 其他 API 错误: 抛 K8sAPIError
        """
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_cluster_custom_object(
                    group=self._GROUP,
                    version=self._VERSION,
                    plural=self._PLURAL,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                logger.info("kueue.cluster_queue.not_found", name=name)
                return None
            logger.warning(
                "kueue.get_cluster_queue.api_error",
                name=name,
                status=exc.status,
                reason=exc.reason,
            )
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("kueue.get_cluster_queue.unexpected", name=name, err=str(exc))
            raise K8sAPIError("Unknown", str(exc)) from exc

        data = _to_primitive(resp) if hasattr(resp, "to_dict") else resp
        status_ = data.get("status") or {}
        logger.info(
            "kueue.get_cluster_queue.ok",
            name=name,
            admitted=status_.get("admittedWorkloads", 0),
            pending=status_.get("pendingWorkloads", 0),
        )
        return status_
