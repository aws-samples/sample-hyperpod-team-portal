"""AWS ComputeQuota dict (PascalCase) ↔ ComputeQuota schema (snake_case).

职责: 纯翻译函数, 不做网络调用, 不抛业务语义异常.
缺字段时用安全默认值 (0 / "" / 枚举默认), 由 orchestration 层判断是否构成错误.
"""

from __future__ import annotations

from typing import Any

from app.modules.quota.api.schemas import (
    AbsoluteBorrowLimit,
    ClusterQuotaList,
    ClusterQuotaTotals,
    ComputeQuota,
    ComputeQuotaResource,
    ComputeQuotaTarget,
    ResourceSharingConfig,
)
from app.modules.quota.domain.formulas import aggregate_totals

# ============================================================
# AWS dict (PascalCase) → Pydantic (snake_case)
# ============================================================

def aws_resource_to_schema(d: dict[str, Any]) -> ComputeQuotaResource:
    """ComputeQuotaResources[] 元素."""
    return ComputeQuotaResource(
        instance_type=d.get("InstanceType", ""),
        count=int(d.get("Count") or 0),
        accelerators=int(d.get("Accelerators") or 0),
        v_cpu=float(d.get("VCpu") or 0.0),
        memory_in_gi_b=float(d.get("MemoryInGiB") or 0.0),
    )


def aws_borrow_limit_to_schema(d: dict[str, Any]) -> AbsoluteBorrowLimit:
    return AbsoluteBorrowLimit(
        instance_type=d.get("InstanceType", ""),
        count=d.get("Count"),
        accelerators=d.get("Accelerators"),
        v_cpu=d.get("VCpu"),
        memory_in_gi_b=d.get("MemoryInGiB"),
    )


def aws_sharing_to_schema(d: dict[str, Any] | None) -> ResourceSharingConfig:
    if not d:
        return ResourceSharingConfig()
    return ResourceSharingConfig(
        strategy=d.get("Strategy") or "LendAndBorrow",
        borrow_limit=d.get("BorrowLimit"),
        absolute_borrow_limits=[
            aws_borrow_limit_to_schema(x)
            for x in (d.get("AbsoluteBorrowLimits") or [])
        ],
    )


def aws_target_to_schema(d: dict[str, Any]) -> ComputeQuotaTarget:
    return ComputeQuotaTarget(
        team_name=d.get("TeamName", ""),
        # AWS 不传 FairShareWeight 时 describe 回填 1
        fair_share_weight=int(d.get("FairShareWeight") or 1),
    )


def aws_quota_to_schema(d: dict[str, Any]) -> ComputeQuota:
    """把 AWS describe_compute_quota / list summary dict 转成 ComputeQuota.

    兼容两种 shape:
    - describe_compute_quota 返: 顶层平铺 + ComputeQuotaConfig 子对象
    - list_compute_quotas.ComputeQuotaSummaries[] 元素: 相同结构
    """
    config = d.get("ComputeQuotaConfig") or {}
    resources_raw = config.get("ComputeQuotaResources") or []
    return ComputeQuota(
        compute_quota_arn=d.get("ComputeQuotaArn", ""),
        compute_quota_id=d.get("ComputeQuotaId", ""),
        name=d.get("Name", ""),
        description=d.get("Description"),
        cluster_arn=d.get("ClusterArn", ""),
        activation_state=d.get("ActivationState") or "Enabled",
        status=d.get("Status") or "Created",
        compute_quota_version=int(d.get("ComputeQuotaVersion") or 1),
        resources=[aws_resource_to_schema(r) for r in resources_raw],
        sharing_config=aws_sharing_to_schema(config.get("ResourceSharingConfig")),
        preempt_team_tasks=config.get("PreemptTeamTasks") or "LowerPriority",
        target=aws_target_to_schema(d.get("ComputeQuotaTarget") or {}),
        creation_time=d.get("CreationTime"),
        last_modified_time=d.get("LastModifiedTime"),
    )


# ============================================================
# Pydantic → AWS PascalCase (Create/Update payload)
# ============================================================

def schema_resource_to_aws(r: ComputeQuotaResource) -> dict[str, Any]:
    """Pydantic resource → AWS ComputeQuotaResources[] 元素.

    SageMaker 约束: Count 与 (Accelerators/VCpu/MemoryInGiB) **互斥**, 二选一.
    - Count > 0: 按整实例数配额 (PoC 主路径), 只发 Count.
    - Count 缺省 (<=0): 按细粒度资源配额, 发 accelerators/vcpu/memory.

    describe_compute_quota 回的数据 AWS 会自动补全细粒度字段 (按 instance
    type 推算), 若原样回传 update 会触发:
        ValidationException: Count cannot be specified together with
        accelerators, vCpuAmount, or memoryInGiB
    故这里按 Count 有无严格二选一.
    """
    out: dict[str, Any] = {"InstanceType": r.instance_type}
    if r.count and r.count > 0:
        out["Count"] = r.count
        return out
    # 无 Count → 走细粒度
    if r.accelerators:
        out["Accelerators"] = r.accelerators
    if r.v_cpu:
        out["VCpu"] = r.v_cpu
    if r.memory_in_gi_b:
        out["MemoryInGiB"] = r.memory_in_gi_b
    return out


def schema_sharing_to_aws(s: ResourceSharingConfig) -> dict[str, Any]:
    """BorrowLimit 与 AbsoluteBorrowLimits 互斥 · 优先后者."""
    out: dict[str, Any] = {"Strategy": s.strategy}
    if s.absolute_borrow_limits:
        out["AbsoluteBorrowLimits"] = [
            {
                k: v
                for k, v in {
                    "InstanceType": b.instance_type,
                    "Count": b.count,
                    "Accelerators": b.accelerators,
                    "VCpu": b.v_cpu,
                    "MemoryInGiB": b.memory_in_gi_b,
                }.items()
                if v is not None
            }
            for b in s.absolute_borrow_limits
        ]
    elif s.borrow_limit is not None:
        out["BorrowLimit"] = s.borrow_limit
    return out


def build_quota_config_payload(
    resources: list[ComputeQuotaResource],
    sharing: ResourceSharingConfig,
    preempt: str,
) -> dict[str, Any]:
    """组装 CreateComputeQuota/UpdateComputeQuota 的 ComputeQuotaConfig 字段."""
    return {
        "ComputeQuotaResources": [schema_resource_to_aws(r) for r in resources],
        "ResourceSharingConfig": schema_sharing_to_aws(sharing),
        "PreemptTeamTasks": preempt,
    }


# ============================================================
# 聚合 cluster totals
# ============================================================

def compute_cluster_totals(quotas: list[ComputeQuota]) -> ClusterQuotaTotals:
    """按 resources[].count × accelerators/v_cpu/memory 聚合跨 team 总量."""
    rows: list[tuple[int, int, float, float]] = [
        (r.count, r.accelerators, r.v_cpu, r.memory_in_gi_b)
        for q in quotas
        for r in q.resources
    ]
    total_accel, total_vcpu, total_mem = aggregate_totals(rows)
    return ClusterQuotaTotals(
        total_accelerators=total_accel,
        total_v_cpu=total_vcpu,
        total_memory_in_gi_b=total_mem,
    )


def build_cluster_quota_list(
    cluster_arn: str,
    cluster_tag: str,
    quotas: list[ComputeQuota],
) -> ClusterQuotaList:
    """包装成最终 ClusterQuotaList response."""
    return ClusterQuotaList(
        cluster_arn=cluster_arn,
        cluster_tag=cluster_tag,
        quotas=quotas,
        totals=compute_cluster_totals(quotas),
    )
