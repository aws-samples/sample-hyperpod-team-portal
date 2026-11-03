"""Workspace Pydantic Schemas (DDB-only —).

UUID → str: DDB key 是字符串. cluster_id 改用 cluster_arn (str).
created_at / updated_at 改用 ISO8601 string (DDB 存 str).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# AWS ComputeQuotaTarget.TeamName pattern: [a-z0-9]([-a-z0-9]*[a-z0-9]){0,39}
_AWS_TEAM_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9]){0,39}$"

_AWS_QUOTA_SHARING_STRATEGIES = Literal["LendAndBorrow", "Lend", "DontLend"]
_AWS_QUOTA_PREEMPT_POLICIES = Literal["LowerPriority", "Never"]


class QuotaResourceRequest(BaseModel):
    instance_type: str = Field(min_length=1, max_length=64)
    count: int = Field(default=0, ge=0)
    accelerators: int | None = Field(default=None, ge=0)
    v_cpu: float | None = Field(default=None, ge=0)
    memory_in_gi_b: float | None = Field(default=None, ge=0)


class WorkspaceCreate(BaseModel):
    cluster_id: str  # cluster_arn
    name: str = Field(pattern=_AWS_TEAM_NAME_PATTERN, max_length=40)
    display_name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    namespace: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,62}$")

    fair_share_weight: int = Field(default=10, ge=0, le=100)
    # 平台默认: 不借不还, 也不抢占别 team 任务 (M1 简化, 后期可放开)
    sharing_strategy: _AWS_QUOTA_SHARING_STRATEGIES = "DontLend"
    preempt_team_tasks: _AWS_QUOTA_PREEMPT_POLICIES = "Never"
    resources: list[QuotaResourceRequest] = Field(default_factory=list)


class WorkspaceUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class WorkspaceSummary(BaseModel):
    """Workspace 列表项.

    PR feat/no-users-table-username-as-id 起 ws 无 owner 概念:
        owner_user_id 字段保留为兼容前端 TS, 但永远空字符串.
        创建人审计请走 AuditLog 表.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    cluster_id: str
    name: str
    display_name: str
    namespace: str
    description: str | None = None
    owner_user_id: str = ""  # deprecated, always empty
    status: str = "active"
    created_at: str
    updated_at: str


class WorkspaceDetail(BaseModel):
    """Workspace 详情.

    PR feat/no-users-table-username-as-id 起 ws 无 owner 概念:
        owner_user_id / owner_display_name / owner_email 都保留为兼容前端 TS,
        但永远空字符串.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    cluster_id: str
    cluster_tag: str
    name: str
    display_name: str
    namespace: str
    description: str | None = None
    owner_user_id: str = ""  # deprecated, always empty
    owner_display_name: str = ""  # deprecated, always empty
    owner_email: str = ""  # deprecated, always empty
    status: str = "active"
    member_count: int
    quota_summary: dict[str, Any] | None = None
    sagemaker_compute_quota_id: str | None = None
    sagemaker_compute_quota_arn: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


# ===== Member =====

class MemberAdd(BaseModel):
    """加成员请求.

    user_id 字段语义: = IdC username (与 token identities[0].userId 一致).
    任命人知道 IdC username 但不知道 cognito_sub, 直接传 username.

    role 两种:
      - admin: workspace 管理员, 能加/减成员, 能调队列优先级
      - member: 普通成员, 能创建任务/开发机
    """
    user_id: str
    role: Literal["admin", "member"]


class MemberUpdate(BaseModel):
    role: Literal["admin", "member"]


class MemberResponse(BaseModel):
    """成员列表项.

    user_id = IdC username. email / display_name 来自 WorkspaceMembers 表
    写入时的快照 (改名后陈旧).
    """
    user_id: str
    email: str
    display_name: str
    role: Literal["admin", "member"]
    joined_at: str
