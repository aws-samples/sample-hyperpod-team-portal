"""Workspace 列表可见性决策 (越权漏洞修复, 2026-06-14).

GET /workspaces 不能再信前端传的 user_id 决定可见范围。
可见范围只由"已认证身份"决定:
    - 平台超管 (is_admin)         → 全部 ws (effective_user_id = None)
    - 普通用户                    → 只看自己 owner+member 的 ws (= 自己的 username)
"""
from __future__ import annotations

from typing import Any


def effective_visibility_user_id(current_user: dict[str, Any]) -> str | None:
    """返回喂给 crud.list_workspaces(user_id=...) 的过滤值。

    None  = 不按 user 过滤 (拿全部) — 仅平台超管。
    非 None = 限定到该 username — 普通用户。
    """
    if current_user.get("is_admin"):
        return None
    return str(
        current_user.get("user_id")
        or current_user.get("username")
        or current_user.get("id")
        or ""
    )
