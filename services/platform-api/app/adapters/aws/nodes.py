"""HyperPod ListClusterNodes / DescribeClusterNode — 替代 RDS node_status 静态字段.

注意:
    - GPU/CPU 用量 *不在* 这些 API 里, 必须从 K8s Node + Metrics Server 拿
      (见 app/adapters/k8s/node.py). 本模块只覆盖 AWS 侧的"节点元信息".
    - 30s TTL 缓存; 100 节点大屏 5s 刷新 → 命中率 ≥95%.
"""

from __future__ import annotations

from typing import Any

import aioboto3

from app.adapters.aws._ttl_cache import TtlCache
from app.core.config import get_settings

_list_cache: TtlCache[list[dict[str, Any]]] | None = None
_describe_cache: TtlCache[dict[str, Any]] | None = None


def _get_list_cache() -> TtlCache[list[dict[str, Any]]]:
    global _list_cache
    if _list_cache is None:
        ttl = float(get_settings().cache_ttl_nodes or 30)
        _list_cache = TtlCache[list[dict[str, Any]]](ttl_seconds=ttl)
    return _list_cache


def _get_describe_cache() -> TtlCache[dict[str, Any]]:
    global _describe_cache
    if _describe_cache is None:
        ttl = float(get_settings().cache_ttl_nodes or 30)
        _describe_cache = TtlCache[dict[str, Any]](ttl_seconds=ttl)
    return _describe_cache


def reset_cache() -> None:
    global _list_cache, _describe_cache
    _list_cache = None
    _describe_cache = None


async def _list_uncached(cluster_name: str) -> list[dict[str, Any]]:
    s = get_settings()
    session = aioboto3.Session()
    nodes: list[dict[str, Any]] = []
    next_token: str | None = None
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        while True:
            kwargs: dict[str, Any] = {"ClusterName": cluster_name, "MaxResults": 100}
            if next_token:
                kwargs["NextToken"] = next_token
            resp = await client.list_cluster_nodes(**kwargs)
            nodes.extend(resp.get("ClusterNodeSummaries") or [])
            next_token = resp.get("NextToken")
            if not next_token:
                break
    return nodes


async def list_cluster_nodes(cluster_name: str | None = None) -> list[dict[str, Any]]:
    name = cluster_name or get_settings().hyperpod_cluster_name
    if not name:
        raise ValueError("hyperpod_cluster_name not configured")
    return await _get_list_cache().get_or_load(name, lambda: _list_uncached(name))


async def _describe_uncached(cluster_name: str, node_id: str) -> dict[str, Any]:
    s = get_settings()
    session = aioboto3.Session()
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        resp = await client.describe_cluster_node(ClusterName=cluster_name, NodeId=node_id)
    return resp.get("NodeDetails", {})


async def describe_cluster_node(
    node_id: str, cluster_name: str | None = None
) -> dict[str, Any]:
    name = cluster_name or get_settings().hyperpod_cluster_name
    if not name:
        raise ValueError("hyperpod_cluster_name not configured")
    return await _get_describe_cache().get_or_load(
        f"{name}:{node_id}", lambda: _describe_uncached(name, node_id)
    )
