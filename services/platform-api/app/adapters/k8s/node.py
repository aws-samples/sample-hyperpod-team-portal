"""Node 列表适配器 (只读).

职责:
    list_nodes 返扁平 dict list, 给 cluster 同步模块用. 只读, 不 watch.

对应 K8s 资源:
    core/v1 Node (内建资源, 非 CR)

官方 URL:
    https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.31/#node-v1-core
"""

from __future__ import annotations

import re
from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.core.logging import get_logger

from .base import K8sClientBase, _to_primitive
from .errors import K8sAPIError

logger = get_logger(__name__)


# providerID 末尾抓 instance id,兼容:
#   aws:///usw2-az2/sagemaker/cluster/hyperpod-abcd1234efgh-i-0123456789abcdef0
#   aws:///us-west-2a/i-0123456789abcdef0
_INSTANCE_ID_RE = re.compile(r"(i-[0-9a-f]{8,})")


def _extract_instance_id(provider_id: str | None, annotations: dict[str, str] | None) -> str | None:
    if provider_id:
        m = _INSTANCE_ID_RE.search(provider_id)
        if m:
            return m.group(1)
    # fallback: csi annotation 里也有 instance id
    if annotations:
        for v in annotations.values():
            if v and "i-" in v:
                m = _INSTANCE_ID_RE.search(v)
                if m:
                    return m.group(1)
    return None


def _parse_cpu_millicores(raw: str | None) -> int | None:
    """'31850m' -> 31850; '32' -> 32000; None -> None"""
    if not raw:
        return None
    s = str(raw).strip()
    if s.endswith("m"):
        try:
            return int(s[:-1])
        except ValueError:
            return None
    try:
        return int(float(s) * 1000)
    except ValueError:
        return None


def _parse_memory_mib(raw: str | None) -> int | None:
    """'120555972Ki' -> MiB (floor division); 兼容 Mi/Gi/Ki/纯字节."""
    if not raw:
        return None
    s = str(raw).strip()
    mult = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}
    for suf, bytes_per in mult.items():
        if s.endswith(suf):
            try:
                return int(int(s[: -len(suf)]) * bytes_per // (1024**2))
            except ValueError:
                return None
    try:
        return int(int(s) // (1024**2))
    except ValueError:
        return None


def _is_ready(conditions: list[dict[str, Any]] | None) -> bool:
    if not conditions:
        return False
    for c in conditions:
        if c.get("type") == "Ready":
            return c.get("status") == "True"
    return False


class NodeMixin(K8sClientBase):
    """core/v1 Node 只读操作."""

    async def list_nodes(self) -> list[dict[str, Any]]:
        """返每个 node 的扁平 dict (见各字段 inline comment)."""
        try:
            await self._load_config()
            async with ApiClient() as api:
                v1 = k8s_client.CoreV1Api(api)
                resp = await v1.list_node()
        except ApiException as exc:
            logger.warning("k8s.list_nodes.api_error", status=exc.status, reason=exc.reason)
            raise K8sAPIError(f"ApiException.{exc.status}", exc.reason or str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("k8s.list_nodes.unexpected", err=str(exc))
            raise K8sAPIError("Unknown", str(exc)) from exc

        items = _to_primitive(resp).get("items", [])
        result: list[dict[str, Any]] = []
        for item in items:
            meta = item.get("metadata") or {}
            spec = item.get("spec") or {}
            status_ = item.get("status") or {}
            labels = meta.get("labels") or {}
            annotations = meta.get("annotations") or {}
            alloc = status_.get("allocatable") or {}
            conditions = status_.get("conditions") or []
            node_info = status_.get("node_info") or status_.get("nodeInfo") or {}

            result.append(
                {
                    "k8s_node_name": meta.get("name"),
                    "instance_id": _extract_instance_id(spec.get("provider_id") or spec.get("providerID"), annotations),
                    "instance_type": labels.get("node.kubernetes.io/instance-type"),
                    "instance_group_name": labels.get("sagemaker.amazonaws.com/instance-group-name"),
                    "availability_zone": labels.get("topology.kubernetes.io/zone"),
                    "ready": _is_ready(conditions),
                    "gpu_allocatable": int(alloc.get("nvidia.com/gpu", 0) or 0),
                    "cpu_allocatable_millicores": _parse_cpu_millicores(alloc.get("cpu")),
                    "memory_allocatable_mib": _parse_memory_mib(alloc.get("memory")),
                    "kubelet_version": node_info.get("kubelet_version") or node_info.get("kubeletVersion"),
                    "creation_timestamp": (
                        meta.get("creation_timestamp").isoformat()
                        if hasattr(meta.get("creation_timestamp"), "isoformat")
                        else meta.get("creation_timestamp") or meta.get("creationTimestamp")
                    ),
                    "sagemaker_health_status": labels.get("sagemaker.amazonaws.com/node-health-status"),
                    "labels": labels,
                }
            )

        logger.info("k8s.list_nodes.ok", count=len(result))
        return result
