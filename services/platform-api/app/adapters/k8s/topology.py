"""Kueue ResourceFlavor / Topology 只读适配器.

两者均 cluster-scoped (用 get_cluster_custom_object), 且版本号不同:
    resourceflavors.kueue.x-k8s.io/v1beta1     .spec.topologyName → Topology 名
    topologies.kueue.x-k8s.io/v1alpha1         .spec.levels[].nodeLabel → 层级名

都由 HyperPod add-on 建, 不保证与节点实际 label 一致。

404 返 None 不抛错: 机型不在配额里时没有对应 flavor, 属正常。
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


class TopologyMixin(K8sClientBase):
    """ResourceFlavor / Topology 只读 (拓扑层级链路)。"""

    _KUEUE_GROUP = "kueue.x-k8s.io"
    _FLAVOR_VERSION = "v1beta1"
    _FLAVOR_PLURAL = "resourceflavors"
    _TOPOLOGY_VERSION = "v1alpha1"
    _TOPOLOGY_PLURAL = "topologies"

    async def _get_cluster_kueue_cr(
        self, version: str, plural: str, name: str
    ) -> dict[str, Any] | None:
        """读 cluster-scoped Kueue CR, 404 → None。"""
        try:
            await self._load_config()
            async with ApiClient() as api:
                co = k8s_client.CustomObjectsApi(api)
                resp = await co.get_cluster_custom_object(
                    group=self._KUEUE_GROUP,
                    version=version,
                    plural=plural,
                    name=name,
                )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise K8sAPIError(
                f"ApiException.{exc.status}", exc.reason or str(exc)
            ) from exc
        return _to_primitive(resp) if hasattr(resp, "to_dict") else resp

    async def get_resource_flavor(self, name: str) -> dict[str, Any] | None:
        """读 ResourceFlavor (flavor 名 == 机型名)。"""
        return await self._get_cluster_kueue_cr(
            self._FLAVOR_VERSION, self._FLAVOR_PLURAL, name
        )

    async def get_topology(self, name: str) -> dict[str, Any] | None:
        """读 Topology (v1alpha1)。"""
        return await self._get_cluster_kueue_cr(
            self._TOPOLOGY_VERSION, self._TOPOLOGY_PLURAL, name
        )
