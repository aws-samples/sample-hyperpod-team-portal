"""任务总览响应 schema。"""
from __future__ import annotations

from pydantic import BaseModel


class TaskStats(BaseModel):
    running_starting: int
    queued: int


class TaskRow(BaseModel):
    id: str
    kind: str  # dev | train | inference
    name: str | None = None
    k8s_name: str | None = None  # CR name (= cr_name, 前端改优先级调 priority 模块端点用)
    status: str | None = None  # 原始 CR phase 字符串 (不再 unified 归一)
    kueue_status: str | None = None  # Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像); 前端 queueScope/可编辑判定用
    creator: str | None = None
    priority_class: str | None = None
    priority_value: int | None = None  # WPC 数值 rank (后端按 priority_class 查 K8s WPC 填; 无/未知 → None)
    gpu_spec: str
    created_at: str | None = None
    started_at: str | None = None


class TaskOverviewResponse(BaseModel):
    can_edit_priority: bool = False
    stats: TaskStats
    tasks: list[TaskRow]
