"""认证 / 鉴权 (Cognito JWT + API Token 双路径)

设计 (PR feat/no-users-table-username-as-id, 2026-05-20):
    - 不再有 DDB Users 表 (删, Cognito + IdC 是 user 数据源)
    - 业务层主 user ID 用 IdC username (来自 token identities[0].userId)
    - is_admin 真值 = PlatformAdmins 表 exists(username)
    - email / display_name 直接从 token claim 拿 (改 email 后下次刷新 token 自动更新)

两条认证路径 (汇流到同一 username):
- cognito:   验 Authorization Bearer 里的 Cognito ID token,
             从 token 解出 username/email/display_name + 查 PlatformAdmins 标 is_admin
- api-token: 脚本 headless, Bearer hypd_xxx → 反查 username + 实时查 is_admin
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.core.cognito_jwt import verify_cognito_id_token
from app.core.config import Settings, get_settings
from app.core.i18n import t
from app.core.token_util import TOKEN_PREFIX, hash_token
from app.repositories import api_tokens as api_tokens_repo
from app.repositories import platform_admins as platform_admins_repo

logger = logging.getLogger("platform_api.security")


def _extract_bearer(auth_header: str) -> str | None:
    """从 Authorization 头取 Bearer token; 无/空/非 Bearer 返 None。"""
    if not auth_header.lower().startswith("bearer "):
        return None
    raw = auth_header[7:].strip()
    return raw or None


def resolve_user_token(auth_header: str, query_token: str | None) -> str | None:
    """选用户 token: 优先 Authorization Bearer, 回退 ?access_token= query。

    SSE / 下载链接 (EventSource、浏览器直开下载) 无法设 Authorization 头,
    只能把 token 放 query。普通 API 仍走 header。
    """
    header_tok = _extract_bearer(auth_header)
    if header_tok:
        return header_tok
    qt = (query_token or "").strip()
    return qt or None


async def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency · 解析当前用户身份.

    返回 dict 兼容现有 UserResponse schema, 字段:
        - id / user_id / username: 都等于 IdC username (业务层主 ID)
        - cognito_sub: Cognito UUID (一般业务层不用)
        - email, display_name: 来自 token claim (改 email 后下次刷新自动更新)
        - is_admin: PlatformAdmins.exists(username) 结果
        - status / default_uid 等: 兼容字段, 都是默认值

    认证路径:
    - cognito: 验 Bearer token, 从 token 派生 user dict
    - api-token: Bearer hypd_xxx → 反查 username + 实时查 is_admin
    """
    settings = get_settings()

    # API Token 路径 (脚本 headless): Bearer hypd_xxx
    raw = _extract_bearer(request.headers.get("authorization", ""))
    if raw and raw.startswith(TOKEN_PREFIX):
        return await _api_token_user(raw)

    return await _cognito_user(request, settings)


async def get_current_user_allow_query(request: Request) -> dict[str, Any]:
    """同 get_current_user, 但额外支持 ?access_token= query token。

    用于 SSE / 文件下载端点 (EventSource、浏览器直开下载链接无法设
    Authorization 头)。token 来源: 优先 header Bearer, 回退 query。
    解析后与 header 路径完全一致 (api-token / cognito 双路 + 实时查 is_admin)。
    """
    settings = get_settings()
    token = resolve_user_token(
        request.headers.get("authorization", ""),
        request.query_params.get("access_token"),
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Bearer token or access_token",
        )
    if token.startswith(TOKEN_PREFIX):
        return await _api_token_user(token)
    return await _user_from_cognito_token(token, settings)


async def require_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """FastAPI dependency · 仅平台超级管理员可继续 (PlatformAdmins 表 exists).

    用于 workspace.create / delete 等"平台级"写接口的 gate.
    非 admin 返 403; admin 透传 current_user dict 给路由.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="forbidden: platform admin required",
        )
    return current_user


# ============================================================
# API Token 路径 (脚本 headless)
# ============================================================

async def _api_token_user(token: str) -> dict[str, Any]:
    """API Token → user dict. 与 _cognito_user 同形状, 多 source='apitoken'.

    middleware 已验过有效性 (hash 命中 + 未过期); 这里防御性再查一次拿 username.
    权限 (is_admin) 实时查 PlatformAdmins — 与浏览器路径完全一致, 离职/降权即时生效.
    """
    rec = await api_tokens_repo.get_by_hash(hash_token(token))
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token invalid or revoked",
        )
    username = rec["username"]
    is_admin = await platform_admins_repo.exists(username)
    return {
        "id": username,
        "user_id": username,
        "username": username,
        "cognito_sub": "",
        "email": "",
        "display_name": username,
        "is_admin": is_admin,
        "source": "apitoken",
        "status": "active",
        "default_uid": 10001,
        "default_gid": 10001,
        "last_login_at": None,
        "created_at": "",
        "updated_at": "",
    }


# ============================================================
# Cognito 路径 (M2)
# ============================================================

async def _cognito_user(request: Request, settings: Settings) -> dict[str, Any]:
    """从 Authorization Bearer 拿 Cognito ID token, 验签 + 派生 user dict."""
    token = _extract_bearer(request.headers.get("authorization", ""))
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Bearer token",
        )
    return await _user_from_cognito_token(token, settings)


async def _user_from_cognito_token(
    token: str, settings: Settings
) -> dict[str, Any]:
    """验 Cognito ID token + 派生 user dict (header / query token 共用)."""
    claims = verify_cognito_id_token(token, settings)

    if not claims.username:
        # token identities[0].userId 是空 — 说明 IdC SAML attribute mapping 错了
        # 应该把 Subject 配成 ${user:subject}; 出现这条说明配置漂移
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("core.cognito_missing_idc_username"),
        )

    is_admin = await platform_admins_repo.exists(claims.username)

    return {
        # ID 字段三个别名都填上 (兼容现有 UserResponse / 业务代码)
        "id": claims.username,
        "user_id": claims.username,
        "username": claims.username,
        "cognito_sub": claims.sub,
        # 实时字段 (从 token claim 直接拿)
        "email": claims.email,
        "display_name": claims.name or claims.username,
        "is_admin": is_admin,
        # 兼容 UserResponse 的占位字段 (前端如果还在读, 不破)
        "status": "active",
        "default_uid": 10001,
        "default_gid": 10001,
        "last_login_at": None,
        "created_at": "",
        "updated_at": "",
    }


def _ws_username(user: dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("username") or user.get("id") or "")


async def _get_membership(ws_id: str, username: str) -> dict[str, Any] | None:
    # 懒导入: workspace.api.router 在 import 期就 import 本模块, 顶层 import ws_crud 会循环。
    from app.modules.workspace.persistence import crud as ws_crud
    return await ws_crud.get_membership(None, ws_id, username)


async def is_ws_admin(ws_id: str, user: dict[str, Any] | None) -> bool:
    """ws admin = 平台超管 (is_admin) 或 该 ws 的 member.role == 'admin'。"""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    m = await _get_membership(ws_id, _ws_username(user))
    return bool(m and m.get("role") == "admin")


async def assert_ws_admin(ws_id: str, user: dict[str, Any]) -> None:
    """非 (超管 OR ws admin) 抛 403。"""
    if not await is_ws_admin(ws_id, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("core.ws_admin_required"),
        )


async def is_ws_member(ws_id: str, user: dict[str, Any] | None) -> bool:
    """ws member = 平台超管 (is_admin) 或该 ws 的任意 role 成员 (含 owner=admin)。

    与 is_ws_admin 的区别: 这里 role 不限 (member 也算), 用于"能否查看 ws 及其下
    资源"的读闸门; is_ws_admin 仅 role==admin, 用于 ws 内写/管理操作。
    """
    if not user:
        return False
    if user.get("is_admin"):
        return True
    m = await _get_membership(ws_id, _ws_username(user))
    return m is not None


async def assert_ws_member(ws_id: str, user: dict[str, Any]) -> None:
    """非 (超管 OR ws 成员) 抛 403。"""
    if not await is_ws_member(ws_id, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("core.ws_member_required"),
        )
