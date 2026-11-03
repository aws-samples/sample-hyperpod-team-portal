"""SageMaker HyperPod DescribeCluster — 替代 RDS cluster + instance_group 表.

cluster + instance_group 字段 100% 由 DescribeCluster 返回.
30s TTL 缓存避免大屏 5s 刷新触发 throttle (DescribeCluster 默认 ~5 RPS).
"""

from __future__ import annotations

from typing import Any

import aioboto3

from app.adapters.aws._ttl_cache import TtlCache
from app.core.config import get_settings

# 默认 30s; 可通过 settings.cache_ttl_cluster_summary 覆盖.
_cache: TtlCache[dict[str, Any]] | None = None


def _get_cache() -> TtlCache[dict[str, Any]]:
    global _cache
    if _cache is None:
        ttl = float(get_settings().cache_ttl_cluster_summary or 30)
        _cache = TtlCache[dict[str, Any]](ttl_seconds=ttl)
    return _cache


def reset_cache() -> None:
    """测试用."""
    global _cache
    _cache = None


async def _describe_uncached(cluster_name: str) -> dict[str, Any]:
    s = get_settings()
    session = aioboto3.Session()
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        return await client.describe_cluster(ClusterName=cluster_name)


async def describe_cluster(cluster_name: str | None = None) -> dict[str, Any]:
    """Returns 完整 DescribeCluster response dict (boto3 风格 PascalCase keys).

    cluster_name 不传则取 settings.hyperpod_cluster_name.
    """
    name = cluster_name or get_settings().hyperpod_cluster_name
    if not name:
        raise ValueError("hyperpod_cluster_name not configured")
    return await _get_cache().get_or_load(name, lambda: _describe_uncached(name))


async def list_instance_groups(cluster_name: str | None = None) -> list[dict[str, Any]]:
    """提取 InstanceGroups + RestrictedInstanceGroups 合并."""
    desc = await describe_cluster(cluster_name)
    igs = list(desc.get("InstanceGroups") or [])
    igs.extend(desc.get("RestrictedInstanceGroups") or [])
    return igs


async def get_cluster_summary(cluster_name: str | None = None) -> dict[str, Any]:
    """RDS cluster 表的字段映射 (供前端列表/详情页用).

    返回字段 (与原 RDS schema 1:1):
        cluster_tag, type, eks_cluster_name, hyperpod_cluster_arn,
        region, state, created_at
    """
    desc = await describe_cluster(cluster_name)
    arn = desc.get("ClusterArn", "")
    region = arn.split(":")[3] if arn.count(":") >= 3 else get_settings().aws_region
    eks_arn = (desc.get("Orchestrator") or {}).get("Eks", {}).get("ClusterArn", "")
    eks_name = eks_arn.rsplit("/", 1)[-1] if eks_arn else None
    creation = desc.get("CreationTime")
    return {
        "cluster_tag": desc.get("ClusterName"),
        "type": "hyperpod",
        "eks_cluster_name": eks_name,
        "hyperpod_cluster_arn": arn,
        "region": region,
        "state": desc.get("ClusterStatus"),
        "node_recovery": desc.get("NodeRecovery"),
        "created_at": creation.isoformat() if hasattr(creation, "isoformat") else creation,
    }
