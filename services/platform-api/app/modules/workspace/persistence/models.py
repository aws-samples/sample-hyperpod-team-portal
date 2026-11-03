"""Workspace + UserWorkspaceRole 类型 (DDB-only).

历史: SQLAlchemy ORM 模型. 切 DDB 后, 真实数据存在
``app.repositories.workspaces`` (Workspaces 表) +
``app.repositories.workspace_members`` (WorkspaceMembers 表).

Workspace dict 字段 (来源: AWS ComputeQuota + DDB Workspaces):
    workspace_id     str  (DDB PK; 业务上等同 'id')
    cluster_arn      str  (AWS)
    display_name     str  (DDB only)
    owner_user_id    str  (DDB only)
    description      str | None
    metadata_json    dict
    compute_quota_id str
    created_at       str (ISO)
    updated_at       str (ISO)
    + (合成) name / namespace / status / cluster_id (从 ComputeQuota 派生)

UserWorkspaceRole dict 字段:
    workspace_id, user_id, role, joined_at, invited_by
"""

from __future__ import annotations

from typing import Any

Workspace = dict[str, Any]
UserWorkspaceRole = dict[str, Any]

__all__ = ["UserWorkspaceRole", "Workspace"]
