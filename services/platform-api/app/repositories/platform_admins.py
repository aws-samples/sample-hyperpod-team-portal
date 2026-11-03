"""PlatformAdmins Repository — DDB hypd-{prefix}-PlatformAdmins.

设计 (PR feat/no-users-table-username-as-id, 2026-05-20):
    - PK 改用 username (从 IdC 拿, 与 token identities[0].userId 一致)
    - 不依赖被任命人先登录 (任命人通常只知道对方的 IdC username)
    - email/display_name 不在此表存 (Cognito / IdC 是单一数据源, 改名后从 token 实时拿)

签名约定: 全部异步; ts 用 ISO8601 str.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------- 读 ----------

async def exists(username: str) -> bool:
    """username 是否在 super admin 表里 (核心权限检查接口)."""
    item = await base.get_item(tables.PLATFORM_ADMINS_TABLE, {"username": username})
    return item is not None


async def get(username: str) -> dict[str, Any] | None:
    return await base.get_item(tables.PLATFORM_ADMINS_TABLE, {"username": username})


async def list_all() -> list[dict[str, Any]]:
    """列出所有 super admin (规模 ≤20, scan 可接受)."""
    return await base.scan_all(tables.PLATFORM_ADMINS_TABLE)


# ---------- 写 ----------

async def add(
    username: str,
    *,
    granted_by: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """添加一个 super admin. username 已存在则覆盖 (idempotent)."""
    item: dict[str, Any] = {
        "username": username,
        "granted_at": _now_iso(),
        "granted_by": granted_by,
    }
    if notes:
        item["notes"] = notes
    await base.put_item(tables.PLATFORM_ADMINS_TABLE, item)
    return item


async def remove(username: str) -> None:
    """从 super admin 表删除. 不存在不报错 (idempotent)."""
    await base.delete_item(
        tables.PLATFORM_ADMINS_TABLE,
        key={"username": username},
        require_exists=False,
    )
