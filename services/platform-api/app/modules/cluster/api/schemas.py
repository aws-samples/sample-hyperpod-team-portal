"""集群管理 Pydantic schemas (DDB-only).

历史: id 是 RDS UUID. 切 DDB / AWS-as-SoT 后, ``id`` 是 UUID5
(从 cluster_tag 派生的稳定 pseudo-UUID), 但仍以 str 表达.
``created_at`` / ``last_synced_at`` 是 ISO8601 string (来自 AWS).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ClusterBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cluster_tag: str
    type: str
    region: str
    state: str


class ClusterSummary(ClusterBase):
    id: str
    workspace_scope: str = "shared"
    last_synced_at: str | None = None
    created_at: str | None = None


# ===== 集群总览 =====

class HealthSummary(BaseModel):
    schedulable: int = 0
    unhealthy: int = 0
    cordoned: int = 0
    replacing: int = 0


class InstanceGroupSummary(BaseModel):
    group_name: str
    instance_type: str
    count: int
    target: int
    az: str
    gpus_total: int = 0
    gpus_used: int = 0
    gpus_pending: int = 0
    health_summary: HealthSummary


class ClusterTotals(BaseModel):
    nodes_ready: int = 0
    nodes_unhealthy: int = 0
    gpus_total: int = 0
    gpus_used: int = 0
    gpus_used_pct: float = 0.0
    active_workspaces: int = 0
    active_training_jobs: int = 0
    active_inference_services: int = 0


class AdvancedFeature(BaseModel):
    enabled: bool = False
    version: str | None = None


class AdvancedFeatures(BaseModel):
    training_operator: AdvancedFeature = Field(default_factory=AdvancedFeature)
    inference_operator: AdvancedFeature = Field(default_factory=AdvancedFeature)
    tiered_storage: AdvancedFeature = Field(default_factory=AdvancedFeature)
    hami: AdvancedFeature = Field(default_factory=AdvancedFeature)


class ClusterSummaryResponse(ClusterSummary):
    instance_groups: list[InstanceGroupSummary] = Field(default_factory=list)
    totals: ClusterTotals = Field(default_factory=ClusterTotals)
    advanced_features: AdvancedFeatures = Field(default_factory=AdvancedFeatures)


# ===== Cluster CRUD (M2 不再开放, 保留 schema 兼容旧 import) =====

class ClusterCreate(BaseModel):
    cluster_tag: str = Field(min_length=1, max_length=64)
    type: str = Field(pattern="^(hyperpod|eks|eas-inference)$")
    region: str
    state: str = "Creating"
    workspace_scope: str = "shared"
    eks_cluster_name: str | None = None
    hyperpod_cluster_arn: str | None = None
    metadata: dict | None = None


class ClusterUpdate(BaseModel):
    state: str | None = None
    workspace_scope: str | None = None
    metadata: dict | None = None
