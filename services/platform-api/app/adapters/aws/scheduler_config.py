"""SageMaker HyperPod ClusterSchedulerConfig adapter.

优先级档权威源: 由 SageMaker task governance 的 cluster policy 管理,
不再由 platform-api 直接写 K8s WorkloadPriorityClass。

"""

from __future__ import annotations

from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from app.adapters.aws._ttl_cache import TtlCache
from app.core.config import get_settings

_PRIORITY_SUFFIX = "-priority"


def to_wpc_name(bare: str) -> str:
    """裸名 → 集群里实际 WPC 名 (X → X-priority);已带后缀则原样返回。"""
    if bare.endswith(_PRIORITY_SUFFIX):
        return bare
    return f"{bare}{_PRIORITY_SUFFIX}"


def to_bare_name(wpc: str) -> str:
    """WPC 名 → 裸名 (仅剥尾部 -priority,不动名字中间的 -priority 子串)。"""
    if wpc.endswith(_PRIORITY_SUFFIX):
        return wpc[: -len(_PRIORITY_SUFFIX)]
    return wpc


class SchedulerConfigError(RuntimeError):
    """scheduler config 相关错误 (未配置 / 未找到 / 冲突等)."""


# 两级缓存 (长 TTL: cluster arn/config id 变化极少)
_arn_cache: TtlCache[str] | None = None
_id_cache: TtlCache[str] | None = None


def _get_arn_cache() -> TtlCache[str]:
    global _arn_cache
    if _arn_cache is None:
        _arn_cache = TtlCache[str](ttl_seconds=3600.0)  # 1h  # 有意不走 settings: ARN + config-id 近乎永久
    return _arn_cache


def _get_id_cache() -> TtlCache[str]:
    global _id_cache
    if _id_cache is None:
        _id_cache = TtlCache[str](ttl_seconds=3600.0)  # 1h  # 有意不走 settings: ARN + config-id 近乎永久
    return _id_cache


def reset_cache() -> None:
    global _arn_cache, _id_cache
    _arn_cache = None
    _id_cache = None


def _sagemaker_client() -> Any:
    """返回 aioboto3 sagemaker client 的 async context manager. 便于测试 patch."""
    s = get_settings()
    session = aioboto3.Session()
    return session.client("sagemaker", region_name=s.aws_region)


async def _resolve_arn_uncached(cluster_name: str) -> str:
    async with _sagemaker_client() as client:
        resp = await client.describe_cluster(ClusterName=cluster_name)
    arn = resp.get("ClusterArn")
    if not arn:
        raise SchedulerConfigError(
            f"describe-cluster returned no ClusterArn for {cluster_name!r}"
        )
    return arn


async def resolve_cluster_arn(cluster_name: str) -> str:
    """cluster name → ARN. 空 name 直接报错; 结果缓存 1h."""
    if not cluster_name:
        raise SchedulerConfigError(
            "hyperpod_cluster_name is empty; scheduler config API unavailable"
        )
    return await _get_arn_cache().get_or_load(
        cluster_name, lambda: _resolve_arn_uncached(cluster_name)
    )


async def _resolve_id_uncached(cluster_arn: str) -> str:
    # 单集群至多 1 个 scheduler config, 无需分页
    async with _sagemaker_client() as client:
        resp = await client.list_cluster_scheduler_configs(ClusterArn=cluster_arn)
    summaries = resp.get("ClusterSchedulerConfigSummaries") or []
    if not summaries:
        raise SchedulerConfigError(
            f"no cluster policy found for cluster {cluster_arn}; "
            "please create scheduler config in SageMaker console"
        )
    if len(summaries) > 1:
        raise SchedulerConfigError(
            f"multiple scheduler configs found for {cluster_arn}; "
            "platform-api expects exactly one per cluster"
        )
    cid = summaries[0].get("ClusterSchedulerConfigId")
    if not cid:
        raise SchedulerConfigError(
            f"scheduler config summary missing ClusterSchedulerConfigId for {cluster_arn}"
        )
    return cid


async def resolve_config_id(cluster_arn: str) -> str:
    """cluster ARN → scheduler config id. 缓存 1h."""
    return await _get_id_cache().get_or_load(
        cluster_arn, lambda: _resolve_id_uncached(cluster_arn)
    )


async def _describe_config_uncached(config_id: str) -> dict[str, Any]:
    try:
        async with _sagemaker_client() as client:
            return await client.describe_cluster_scheduler_config(
                ClusterSchedulerConfigId=config_id
            )
    except ClientError as exc:
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        raise SchedulerConfigError(
            f"describe-cluster-scheduler-config failed: {msg}"
        ) from exc


async def _apply_priority_classes(
    config_id: str, priorities: list[dict[str, Any]], version: int
) -> None:
    """写回 PriorityClasses (TargetVersion 乐观锁); ClientError → SchedulerConfigError."""
    try:
        async with _sagemaker_client() as client:
            await client.update_cluster_scheduler_config(
                ClusterSchedulerConfigId=config_id,
                TargetVersion=version,
                SchedulerConfig={"PriorityClasses": priorities},
            )
    except ClientError as exc:
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        raise SchedulerConfigError(f"update-cluster-scheduler-config failed: {msg}") from exc


async def _describe_config_with_version(config_id: str) -> tuple[list[dict[str, Any]], int]:
    """返回 (PriorityClasses 列表, 当前 version)."""
    detail = await _describe_config_uncached(config_id)
    priorities = list(
        (detail.get("SchedulerConfig") or {}).get("PriorityClasses") or []
    )
    version = int(detail.get("ClusterSchedulerConfigVersion") or 0)
    return priorities, version


async def upsert_priority_class(
    hyperpod_cluster_name: str, *, bare_name: str, weight: int
) -> None:
    """建或改档: 存在同名则改 Weight, 不存在则追加. 使用 TargetVersion 乐观锁."""
    arn = await resolve_cluster_arn(hyperpod_cluster_name)
    cid = await resolve_config_id(arn)
    priorities, version = await _describe_config_with_version(cid)
    updated = [p for p in priorities if p.get("Name") != bare_name]
    updated.append({"Name": bare_name, "Weight": int(weight)})
    await _apply_priority_classes(cid, updated, version)


async def delete_priority_class(
    hyperpod_cluster_name: str, *, bare_name: str
) -> None:
    """删档: 从 PriorityClasses 数组移除同名项 (不存在则原样, 仍发一次 update 保持幂等)."""
    arn = await resolve_cluster_arn(hyperpod_cluster_name)
    cid = await resolve_config_id(arn)
    priorities, version = await _describe_config_with_version(cid)
    updated = [p for p in priorities if p.get("Name") != bare_name]
    await _apply_priority_classes(cid, updated, version)


async def list_priority_classes(hyperpod_cluster_name: str) -> list[dict[str, Any]]:
    """列 cluster policy 里的档, 裸名补 -priority 后按 value 降序返回.

    返回项: {name (带 -priority), value (weight 0-100), description (None)}
    """
    arn = await resolve_cluster_arn(hyperpod_cluster_name)
    cid = await resolve_config_id(arn)
    detail = await _describe_config_uncached(cid)
    priorities = (detail.get("SchedulerConfig") or {}).get("PriorityClasses") or []
    rows = [
        {
            "name": to_wpc_name(p["Name"]),
            "value": int(p.get("Weight") or 0),
            "description": None,
        }
        for p in priorities
    ]
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows
