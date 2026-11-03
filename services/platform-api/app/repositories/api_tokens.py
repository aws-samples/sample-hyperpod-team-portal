"""ApiTokens Repository — DDB hypd-{prefix}-ApiTokens.

设计:
    - 每人一把: PK=username 天然唯一
    - 只存 token_hash (sha256), 不存明文
    - token_display 脱敏展示串 (前4后4)
    - expires_at=None 表示永不过期
    - 验证按 token_hash 反查 → GSI token_hash-index

签名约定: 全异步; ts 用 ISO8601 str.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_item(
    *,
    username: str,
    token_hash: str,
    token_display: str,
    created_at: str,
    expires_at: str | None,
) -> dict[str, Any]:
    """构造 DDB item (纯函数, 易测)."""
    return {
        "username": username,
        "token_hash": token_hash,
        "token_display": token_display,
        "created_at": created_at,
        "expires_at": expires_at,
    }


def is_expired(expires_at: str | None, *, now_iso: str | None = None) -> bool:
    """expires_at=None → 永不过期 → False. 否则字典序比较 ISO8601 (== 时间序)."""
    if expires_at is None:
        return False
    now = now_iso if now_iso is not None else _now_iso()
    return expires_at <= now


# ---------- 读 ----------

async def get_by_username(username: str) -> dict[str, Any] | None:
    """查用户当前 token 元数据 (UI 展示用; 不含明文, 含 hash 但前端不展示)."""
    return await base.get_item(tables.API_TOKENS_TABLE, {"username": username})


async def get_by_hash(token_hash: str) -> dict[str, Any] | None:
    """验证用: 按 token_hash 走 GSI 反查. 命中返 item, 否则 None."""
    items = await base.query(
        tables.API_TOKENS_TABLE,
        key_condition_expression="token_hash = :h",
        expression_values={":h": token_hash},
        index_name=tables.API_TOKENS_GSI_HASH,
        limit=1,
    )
    return items[0] if items else None


# ---------- 写 ----------

async def create(
    *,
    username: str,
    token_hash: str,
    token_display: str,
    expires_at: str | None,
) -> dict[str, Any]:
    """生成 token. 条件 attribute_not_exists(username): 已有则抛 ItemAlreadyExists.

    这保证'必须先删才能生成'在 DB 层也成立 (UI 禁用按钮是第一道, 这是第二道).
    """
    item = build_item(
        username=username,
        token_hash=token_hash,
        token_display=token_display,
        created_at=_now_iso(),
        expires_at=expires_at,
    )
    await base.put_item(tables.API_TOKENS_TABLE, item, ensure_new=True)
    return item


async def delete(username: str) -> None:
    """删除用户的 token. 不存在不报错 (幂等)."""
    await base.delete_item(
        tables.API_TOKENS_TABLE,
        key={"username": username},
        require_exists=False,
    )
