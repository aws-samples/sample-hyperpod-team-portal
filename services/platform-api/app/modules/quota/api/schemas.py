"""Quota 模块 Pydantic schemas · 合并自旧 quota/schemas.py + quota_usage/schemas.py.

两套 schema 共用同一 camelCase 基类:
- ComputeQuota family : 映射 AWS DescribeComputeQuota response
- QuotaUsage family   : 映射 Kueue ClusterQueue.status 解析结果

约定:
- Python 侧 snake_case (PEP 8)
- FastAPI 序列化用 alias_generator=to_camel 转 camelCase 给前端

AWS 文档:
https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeComputeQuota.html
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ============================================================
# 基类 · 默认 camelCase alias
# ============================================================

class QuotaModel(BaseModel):
    """所有 quota schema 基类 · 启用 camelCase 别名(前端契约)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ============================================================
# 枚举
# ============================================================

ActivationState = Literal["Enabled", "Disabled"]
QuotaStatus = Literal[
    "Created", "Creating", "CreateFailed",
    "Updating", "Updated", "UpdateFailed",
    "Deleting", "DeleteFailed",
]
ResourceSharingStrategy = Literal["LendAndBorrow", "Lend", "DontLend"]
PreemptTeamTasks = Literal["LowerPriority", "Never"]


# ============================================================
# ComputeQuota 子结构 (AWS 侧)
# ============================================================

class ComputeQuotaResource(QuotaModel):
    """单机型配额项 · 对齐 AWS ComputeQuotaResources[].

    AWS 说明:
    - accelerators 是**每实例**的 GPU/Neuron 数, 不是总数 (总数 = accelerators × count)
    - v_cpu / memory_in_gi_b 是浮点
    """

    instance_type: str = Field(description="ml.g5.8xlarge / ml.c5.2xlarge 等")
    count: int = Field(default=0, ge=0, description="实例数")
    accelerators: int = Field(default=0, ge=0, description="每实例 GPU/Neuron 数")
    v_cpu: float = Field(default=0.0, ge=0.0, description="每实例 vCPU 核数(浮点)")
    memory_in_gi_b: float = Field(default=0.0, ge=0.0, description="每实例内存 GiB(浮点)")
    pool: Literal["gpu", "cpu"] = "cpu"  # GPU/CPU 资源池 (后端按 EC2 GpuInfo 判, 缺省 cpu)
    gpu_spec: str | None = Field(default=None, description="GPU 描述如 '4×A10G', CPU 机型为 null")
    gpu_type: str | None = Field(default=None, description="GPU 型号如 'L4'/'H100', CPU 机型为 null")


class AbsoluteBorrowLimit(QuotaModel):
    """绝对借用上限 · ResourceSharingConfig.AbsoluteBorrowLimits[]."""

    instance_type: str
    count: int | None = None
    accelerators: int | None = None
    v_cpu: float | None = None
    memory_in_gi_b: float | None = None


class ResourceSharingConfig(QuotaModel):
    """借用配置 · BorrowLimit 与 AbsoluteBorrowLimits 互斥."""

    strategy: ResourceSharingStrategy = "LendAndBorrow"
    borrow_limit: int | None = Field(default=None, ge=0, le=10000, description="百分比 0-10000")
    absolute_borrow_limits: list[AbsoluteBorrowLimit] = Field(default_factory=list)


class ComputeQuotaTarget(QuotaModel):
    """目标 team."""

    team_name: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", max_length=40)
    fair_share_weight: int = Field(default=1, ge=0, le=100)


# ============================================================
# 顶层 ComputeQuota
# ============================================================

class ComputeQuota(QuotaModel):
    """一个 team 的完整 ComputeQuota (AWS describe_compute_quota 映射)."""

    compute_quota_arn: str
    compute_quota_id: str
    name: str
    description: str | None = None
    cluster_arn: str
    activation_state: ActivationState = "Enabled"
    status: QuotaStatus = "Created"
    compute_quota_version: int = 1
    resources: list[ComputeQuotaResource] = Field(default_factory=list)
    sharing_config: ResourceSharingConfig = Field(default_factory=ResourceSharingConfig)
    preempt_team_tasks: PreemptTeamTasks = "LowerPriority"
    target: ComputeQuotaTarget
    creation_time: datetime | None = None
    last_modified_time: datetime | None = None


# ============================================================
# Cluster 聚合
# ============================================================

class ClusterQuotaTotals(QuotaModel):
    """跨 team 合计 (baseline · 按 resources[].count × accelerators/v_cpu/... 求和)."""

    total_accelerators: int = 0
    total_v_cpu: float = 0.0
    total_memory_in_gi_b: float = 0.0


class ClusterQuotaList(QuotaModel):
    """整集群的 team 列表."""

    cluster_arn: str
    cluster_tag: str
    quotas: list[ComputeQuota] = Field(default_factory=list)
    totals: ClusterQuotaTotals = Field(default_factory=ClusterQuotaTotals)


# ============================================================
# 写入 payload
# ============================================================

class CreateComputeQuotaPayload(QuotaModel):
    """POST /workspaces/{ws_id}/quota · 新建一个团队配额."""

    name: str = Field(pattern=r"^[a-zA-Z0-9]([-a-zA-Z0-9]*[a-zA-Z0-9])?$", max_length=63)
    description: str | None = Field(default=None, max_length=1024)
    activation_state: ActivationState = "Enabled"
    resources: list[ComputeQuotaResource] = Field(min_length=1, max_length=15)
    sharing_config: ResourceSharingConfig = Field(default_factory=ResourceSharingConfig)
    preempt_team_tasks: PreemptTeamTasks = "LowerPriority"
    target: ComputeQuotaTarget


class UpdateComputeQuotaPayload(QuotaModel):
    """PATCH /workspaces/{ws_id}/quota · 更新配额 (字段全选一).

    注: AWS UpdateComputeQuota 是完整替换语义, 不是 patch.
    orchestration 层会先 describe 当前值, merge payload 后整体 update.
    """

    description: str | None = None
    activation_state: ActivationState | None = None
    resources: list[ComputeQuotaResource] | None = None
    sharing_config: ResourceSharingConfig | None = None
    preempt_team_tasks: PreemptTeamTasks | None = None
    target: ComputeQuotaTarget | None = None


# ============================================================
# Kueue live usage schemas (原 quota_usage/schemas.py 合入)
# ============================================================

class QuotaResourceUsage(QuotaModel):
    """单个 flavor (instance_type) 的当前用量."""

    instance_type: str
    accelerators_used: int = 0
    accelerators_pending: int = 0
    v_cpu_used: float = 0.0
    memory_used_in_gi_b: float = 0.0


class TotalsUsage(QuotaModel):
    """跨 flavor 合计."""

    accelerators: int = 0
    accelerators_pending: int = 0
    v_cpu: float = 0.0
    memory_in_gi_b: float = 0.0


class QuotaUsage(QuotaModel):
    """一个 workspace 的 quota 实时用量."""

    team_name: str
    resources: list[QuotaResourceUsage]
    totals: TotalsUsage
    captured_at: datetime
