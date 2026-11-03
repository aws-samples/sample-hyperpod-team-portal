"""User 路由.

PR feat/no-users-table-username-as-id, 2026-05-20:
    - DDB Users 表已删, user 信息全从 Cognito ID token claim 派生
    - 仅保留 /me endpoint (前端 AuthGate 用, 探测登录态)
    - 列 / 创建 / 改 / 删 user 等老 endpoint 全删 (Cognito + IdC 是 source of truth)
    - 用户在 IdC console 加 / 改 / 删, 不在我们应用里管

PR feat/idc-user-search, 2026-05-26:
    - 新增 idc_router (路径 /api/v1/idc/users), admin 加 ws 成员时实时查 IdC
    - 走 GetUserId + DescribeUser, 精确等值搜索 (M1 200-5000 人都不卡)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.adapters.aws.identitystore import IdcAPIError, find_user
from app.adapters.ddb.base import ItemAlreadyExists
from app.core.i18n import t
from app.core.security import get_current_user, require_admin
from app.core.token_util import generate_token, hash_token, mask_token
from app.modules.user.api.schemas import (
    ApiTokenCreateBody,
    ApiTokenCreated,
    ApiTokenStatus,
    UserResponse,
)
from app.repositories import api_tokens as api_tokens_repo

user_router = APIRouter(tags=["users"])


@user_router.get(
    "/me",
    response_model=UserResponse,
    summary="查当前登录用户",
    description=(
        "前端 AuthGate 用来探测登录态; 也用于顶栏昵称 / 是否显示超管入口.\n\n"
        "字段来源:\n"
        "- `id`: IdC username (业务层主 user ID; 响应体没有单独的 `username` 字段, "
        "也不返 `cognito_sub`)\n"
        "- `email` / `display_name`: 从 Cognito ID token claim 派生 "
        "(API Token 路径下 email 返空串、display_name 用 username 兜底)\n"
        "- `is_admin`: 查 DDB PlatformAdmins 表\n"
        "- `status` / `default_uid` / `default_gid` / `*_at`: 兼容旧前端的固定占位值\n\n"
        "无 DDB Users 表 (feat/no-users-table-username-as-id): Cognito + IdC 是 source of truth."
    ),
    responses={
        401: {"description": "未登录或 token 无效 / 已过期"},
    },
)
async def get_me_endpoint(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    """返当前登录用户.

    从 ID token claim 解 (email/display_name/username) + PlatformAdmins 表查 is_admin。
    API Token 路径: username 来自 token 反查, email/display_name 用 username 兜底。
    """
    return UserResponse.model_validate(current_user)


# ===== 个人 API Token (headless 脚本到人) =====


@user_router.get(
    "/me/api-token",
    response_model=ApiTokenStatus,
    summary="查我的 API Token 状态 (无明文)",
    description=(
        "返 token 是否存在, 以及脱敏 display / 创建时间 / 过期时间. 明文只在创建时返回一次, 此处永不回显.\n\n"
        "用于个人设置页展示 token 卡片 (has / creation info); 无 token 则 `exists=false`."
    ),
    responses={
        401: {"description": "未登录"},
    },
)
async def get_my_api_token(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ApiTokenStatus:
    rec = await api_tokens_repo.get_by_username(current_user["username"])
    if rec is None:
        return ApiTokenStatus(exists=False)
    return ApiTokenStatus(
        exists=True,
        token_display=rec.get("token_display"),
        created_at=rec.get("created_at"),
        expires_at=rec.get("expires_at"),
    )


@user_router.post(
    "/me/api-token",
    response_model=ApiTokenCreated,
    status_code=status.HTTP_201_CREATED,
    summary="生成我的 API Token (headless 脚本用)",
    description=(
        "为当前用户生成一枚 headless API Token, 用于脚本 / CI 免登录调用平台 API.\n\n"
        "- 明文仅本次响应返回一次, 服务端只留 hash + 脱敏 display\n"
        "- `never_expire=true` → 永不过期, 否则用 `expires_at`; 都不给 = 也永不过期\n"
        "- 每人至多一枚 token, 已有则 409 (先 DELETE 再重建)"
    ),
    responses={
        401: {"description": "未登录"},
        409: {"description": "已存在 token, 请先删除后再生成"},
        422: {"description": "expires_at 格式非法"},
    },
)
async def create_my_api_token(
    body: ApiTokenCreateBody,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ApiTokenCreated:
    username = current_user["username"]

    # 过期时间: never_expire 优先; 否则用传入 expires_at (None = 也永不过期)
    expires_at = None if body.never_expire else body.expires_at

    plain = generate_token()
    try:
        item = await api_tokens_repo.create(
            username=username,
            token_hash=hash_token(plain),
            token_display=mask_token(plain),
            expires_at=expires_at,
        )
    except ItemAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=t("user.api_token_exists"),
        )
    return ApiTokenCreated(
        token=plain,  # 明文, 仅此一次
        token_display=item["token_display"],
        created_at=item["created_at"],
        expires_at=item["expires_at"],
    )


@user_router.delete(
    "/me/api-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除我的 API Token",
    description=(
        "删除当前用户的 API Token (删除后再次 GET 会返 `exists=false`).\n\n"
        "**幂等**: 未生成过 token 也返 204."
    ),
    responses={
        401: {"description": "未登录"},
    },
)
async def delete_my_api_token(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    await api_tokens_repo.delete(current_user["username"])


# ===== IdC user search (平台超管 only, 给加成员 Modal 用) =====

idc_router = APIRouter(tags=["idc"])


class IdcUserSummary(BaseModel):
    username: str
    email: str
    display_name: str


@idc_router.get(
    "/idc/users",
    response_model=list[IdcUserSummary],
    summary="搜索 IdC 用户 (精确匹配 username 或 email)",
    description=(
        "**加成员 Modal** 用: 实时向 AWS IAM Identity Center 查用户.\n\n"
        "- M1 走 `GetUserId` + `DescribeUser` 精确等值搜索, 不支持 prefix / contains\n"
        "- 含 `@` 视作 email, 否则视作 username\n"
        "- 返 0 或 1 条 (IdC 内 username / email 全局唯一)\n\n"
        "**权限**: **仅平台超管** (require_admin) — 注意仅 ws 管理员 (非平台超管) "
        "调本接口也会 403, 其加成员流程无法用此搜索."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        502: {"description": "IdC API 调用失败 (AWS 服务异常 / 权限缺失)"},
    },
)
async def search_idc_users_endpoint(
    q: str = Query(min_length=1, max_length=128, description="完整 username 或 email"),
    current_user: dict[str, Any] = Depends(require_admin),
) -> list[IdcUserSummary]:
    """实时查 IdC 用户.

    M1 走 GetUserId 精确等值, 不支持 prefix/contains 搜索. admin 必须输完整
    username 或 完整 email. 含 "@" 视作 email, 否则视作 username.

    返 0 或 1 条 (IdC 一个 username/email 唯一对应一个 user).
    """
    del current_user
    try:
        user = await find_user(q)
    except IdcAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IdC API failed [{exc.code}]: {exc.message}",
        ) from exc

    if user is None:
        return []
    return [
        IdcUserSummary(
            username=user["username"],
            email=user["email"],
            display_name=user["display_name"] or user["username"],
        )
    ]
