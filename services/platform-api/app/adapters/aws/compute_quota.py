"""SageMaker HyperPod ComputeQuota — 替代 RDS workspace 大半字段 + resource_quota 整表.

 + ComputeQuota 是 workspace 的 source-of-truth.
ComputeQuota 字段 → 业务字段映射:
    Name                              → workspace.name
    ComputeQuotaTarget.TeamName       → workspace.namespace
    ClusterArn                        → workspace.cluster_arn
    Description (1024 字符)           → workspace.description (可选)
    ActivationState + Status          → workspace.status
    CreationTime / LastModifiedTime   → workspace.created_at / updated_at
    ComputeQuotaConfig.ComputeQuotaResources[]  → resource_quota.{gpu,cpu,memory}_quota
    ComputeQuotaConfig.PreemptTeamTasks         → resource_quota.preemption_policy

DDB 上仅补 3 个字段: display_name / owner_user_id / metadata_json.
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
        ttl = float(get_settings().cache_ttl_quotas or 60)
        _list_cache = TtlCache[list[dict[str, Any]]](ttl_seconds=ttl)
    return _list_cache


def _get_describe_cache() -> TtlCache[dict[str, Any]]:
    global _describe_cache
    if _describe_cache is None:
        ttl = float(get_settings().cache_ttl_quotas or 60)
        _describe_cache = TtlCache[dict[str, Any]](ttl_seconds=ttl)
    return _describe_cache


def reset_cache() -> None:
    global _list_cache, _describe_cache
    _list_cache = None
    _describe_cache = None


async def _list_uncached(cluster_arn: str | None) -> list[dict[str, Any]]:
    s = get_settings()
    session = aioboto3.Session()
    summaries: list[dict[str, Any]] = []
    next_token: str | None = None
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        while True:
            kwargs: dict[str, Any] = {"MaxResults": 100}
            if cluster_arn:
                kwargs["ClusterArn"] = cluster_arn
            if next_token:
                kwargs["NextToken"] = next_token
            resp = await client.list_compute_quotas(**kwargs)
            summaries.extend(resp.get("ComputeQuotaSummaries") or [])
            next_token = resp.get("NextToken")
            if not next_token:
                break
    return summaries


async def list_compute_quotas(cluster_arn: str | None = None) -> list[dict[str, Any]]:
    cache_key = cluster_arn or "_all"
    return await _get_list_cache().get_or_load(
        cache_key, lambda: _list_uncached(cluster_arn)
    )


async def _describe_uncached(quota_id: str) -> dict[str, Any]:
    s = get_settings()
    session = aioboto3.Session()
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        return await client.describe_compute_quota(ComputeQuotaId=quota_id)


async def describe_compute_quota(quota_id: str) -> dict[str, Any]:
    return await _get_describe_cache().get_or_load(
        quota_id, lambda: _describe_uncached(quota_id)
    )


async def create_compute_quota(
    *,
    name: str,
    cluster_arn: str,
    team_name: str,
    quota_resources: list[dict[str, Any]],
    description: str | None = None,
    preempt_team_tasks: str = "Never",
    fair_share_weight: int | None = None,
) -> dict[str, Any]:
    """创建 ComputeQuota; HyperPod 自动建 namespace + ResourceQuota + Kueue queue.

    quota_resources schema 来自 ComputeQuotaResourceConfig (e.g. InstanceType + Count).
    返回 boto3 raw response (ComputeQuotaArn / ComputeQuotaId).
    """
    s = get_settings()
    session = aioboto3.Session()
    target: dict[str, Any] = {"TeamName": team_name}
    if fair_share_weight is not None:
        target["FairShareWeight"] = fair_share_weight
    payload: dict[str, Any] = {
        "Name": name,
        "ClusterArn": cluster_arn,
        "ComputeQuotaConfig": {
            "ComputeQuotaResources": quota_resources,
            "PreemptTeamTasks": preempt_team_tasks,
        },
        "ComputeQuotaTarget": target,
    }
    if description:
        payload["Description"] = description
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        resp = await client.create_compute_quota(**payload)
    _get_list_cache().invalidate()
    return resp


async def delete_compute_quota(quota_id: str) -> None:
    s = get_settings()
    session = aioboto3.Session()
    async with session.client("sagemaker", region_name=s.aws_region) as client:
        await client.delete_compute_quota(ComputeQuotaId=quota_id)
    _get_list_cache().invalidate()
    _get_describe_cache().invalidate(quota_id)


# ---------- 业务字段映射 helper ----------

def to_workspace_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """ComputeQuotaSummary → workspace 列表行所需字段."""
    creation = summary.get("CreationTime")
    last_mod = summary.get("LastModifiedTime")
    return {
        "name": summary.get("Name"),
        "compute_quota_id": summary.get("ComputeQuotaId"),
        "compute_quota_arn": summary.get("ComputeQuotaArn"),
        "cluster_arn": summary.get("ClusterArn"),
        "namespace": (summary.get("ComputeQuotaTarget") or {}).get("TeamName"),
        "status": summary.get("Status"),
        "activation_state": summary.get("ActivationState"),
        "created_at": creation.isoformat() if hasattr(creation, "isoformat") else creation,
        "updated_at": last_mod.isoformat() if hasattr(last_mod, "isoformat") else last_mod,
    }


def to_quota_resources(detail: dict[str, Any]) -> dict[str, Any]:
    """DescribeComputeQuota → resource_quota 字段."""
    config = detail.get("ComputeQuotaConfig") or {}
    return {
        "preemption_policy": config.get("PreemptTeamTasks"),
        "resources": config.get("ComputeQuotaResources") or [],
        "fair_share_weight": (detail.get("ComputeQuotaTarget") or {}).get("FairShareWeight"),
    }
