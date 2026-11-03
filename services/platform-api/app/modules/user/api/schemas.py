"""User Pydantic Schemas.

PR feat/no-users-table-username-as-id, 2026-05-20:
    - DDB Users 表已删, user 信息全从 Cognito ID token claim 派生
    - UserCreate / UserUpdate 删 (没有"创建/改用户"的概念了, 全在 IdC 管)
    - UserResponse 字段保留兼容 (前端 TS interface 不变), 多余字段返默认值
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserBase):
    """当前用户信息 · /api/v1/users/me 返回.

    数据来源:
    - id / user_id / username: token identities[0].userId (= IdC username)
    - cognito_sub: token sub claim (Cognito UUID, 业务层一般不用)
    - email / display_name: token claim (改 email/改名后下次刷新 token 自动更新)
    - is_admin: PlatformAdmins 表 exists(username) 结果

    兼容字段 (前端老 TS interface 期望存在, 但内容固定):
    - status: 永远 "active"
    - default_uid / default_gid: 永远 10001 (FSx POSIX 已不用, 历史残留)
    - last_login_at / created_at / updated_at: 永远空 (Cognito 内部信息, 不暴露)
    """

    id: str
    email: str
    display_name: str
    status: str = "active"
    default_uid: int = 10001
    default_gid: int = 10001
    is_admin: bool = False
    last_login_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


# ===== 个人 API Token (headless 脚本到人) =====


class ApiTokenStatus(BaseModel):
    """GET /users/me/api-token 返回: 当前 token 状态 (无明文)."""

    exists: bool
    token_display: str | None = None  # hypd_aweb**************cdce
    created_at: str | None = None
    expires_at: str | None = None  # None = 永不过期


class ApiTokenCreateBody(BaseModel):
    """POST body: 过期日期 或 永不过期 (二选一)."""

    expires_at: str | None = Field(
        default=None,
        description="ISO8601 过期时间; never_expire=true 时忽略",
    )
    never_expire: bool = Field(default=False, description="勾选则永不过期")


class ApiTokenCreated(BaseModel):
    """POST 返回: 明文 token (仅此一次) + 元数据."""

    token: str  # 明文, 仅生成时返回一次
    token_display: str
    created_at: str
    expires_at: str | None = None
