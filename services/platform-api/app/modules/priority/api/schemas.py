"""优先级管理 schemas (WorkloadPriorityClass + Workload + 抢占).

纯 K8s 代理, 无 DDB。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 抢占策略 (ClusterQueue.spec.preemption.withinClusterQueue)
PreemptionPolicy = Literal["Never", "LowerPriority"]

# 任务类型枚举 (仅文档用; 实际入参 WorkloadPriorityPatch.task_type 是裸 str 不校验)
TaskType = Literal["dev", "train", "inference"]


# ---------- WorkloadPriorityClass (档位) ----------

class PriorityClassItem(BaseModel):
    name: str                       # WPC 全名 <bare>-priority (DNS-1123 slug)
    value: int                      # SageMaker Weight 0-100, 越大越优先
    description: str | None = None  # 恒 None (SageMaker 官方 API 无此字段)
    in_use_count: int = 0           # 恒 0 (占位, 未做 Workload 引用统计)


class PriorityClassCreate(BaseModel):
    # name = 裸名; SageMaker 会生成 WPC 名 <name>-priority
    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
    value: int = Field(ge=0, le=100)  # SageMaker Weight 范围


class PriorityClassUpdate(BaseModel):
    value: int | None = Field(default=None, ge=0, le=100)


# ---------- Workload (单任务优先级) ----------

class WorkloadItem(BaseModel):
    workload_name: str              # Kueue Workload 名 (带 hash)
    owner_name: str | None = None   # 任务 CR name (ownerReferences)
    owner_kind: str | None = None
    priority: int | None = None     # 当前 priority 快照
    priority_class_name: str | None = None
    admitted: bool = False          # True=running, False=pending
    queue_name: str | None = None


class WorkloadPriorityPatch(BaseModel):
    """改单任务优先级: 选一个档 (按 name), 后端查 value 一并 patch。

    task_type: dev|train|inference — 三类 Workload 关联链不同, 后端据此走对应反查。
        裸 str 不做枚举校验; dynamo 被后端显式拒 (400), 其他未知值反查不到 → 404。
    priority_class_name: 传 GET /priority-classes 返回的全名 (带 -priority 后缀)。
    """

    task_type: str = Field(min_length=1)
    priority_class_name: str = Field(min_length=1)


# ---------- 抢占开关 ----------

class PreemptionState(BaseModel):
    workspace_id: str
    namespace: str
    cluster_queue: str
    within_cluster_queue: PreemptionPolicy


class PreemptionSet(BaseModel):
    within_cluster_queue: PreemptionPolicy
