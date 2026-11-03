"""Quota 模块 · 配额分配 + Kueue 实时用量 (合并自旧 quota + quota_usage).

资产导向拆分 (2026-05-12 · Wave 2 B4):
- domain/          纯函数 (单位换算 · 用量聚合算法)
- orchestration/   跨 AWS + K8s + DB 编排 (allocate / workspace_quota / usage_sync)
- api/             HTTP 路由 + schemas + deps
- response/        AWS dict ↔ Pydantic 翻译 builders

DB 表 ownership: **无独占表**
- resource_quota 表归 `modules/cluster/`, 且 M1 已废弃 (quota 模块直查 AWS ComputeQuota)
- workspace.sagemaker_compute_quota_{id,arn} 由 workspace 模块 own, 这里通过
  workspace_crud API 读, 写操作 TODO 迁到 workspace_crud (见 allocate.py)

HTTP 路径 (完全保留旧版, 只是后端代码合并):
- /api/v1/workspaces/{ws_id}/quota[*]
- /api/v1/workspaces/{ws_id}/quota/usage
- /api/v1/clusters/{cluster_tag}/quotas
"""

from app.modules.quota.orchestration import (
    create_workspace_quota,
    delete_workspace_quota,
    fetch_quota_usage,
    get_workspace_quota,
    list_cluster_quotas,
    update_workspace_quota,
)

__all__ = [
    "create_workspace_quota",
    "delete_workspace_quota",
    "fetch_quota_usage",
    "get_workspace_quota",
    "list_cluster_quotas",
    "update_workspace_quota",
]
