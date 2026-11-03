"""AuditLog Repository — 操作审计 (RDS node_operation_log + 全局 audit 合并).

PK=scope_key  ("ws#<uuid>" / "cluster#<uuid>" / "global")
SK=event_key  "<created_at_iso>#<event_id>" — ISO8601 字典序==时间序

GSI: actor-index PK=actor_user_id SK=created_at — "谁做了啥"
TTL: expire_at (unix epoch, 365 天) — DDB 自动清理

写入仅 append; 修改仅 update_status/update_completion (操作完成回填), 不允许改 actor/operation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.adapters.ddb import base, tables

DEFAULT_TTL_DAYS = 365


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _expire_at(days: int = DEFAULT_TTL_DAYS) -> int:
    return int((datetime.now(UTC) + timedelta(days=days)).timestamp())


# ---------- 读 ----------

async def list_by_scope(
    scope_key: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """时间倒序; scope_key e.g. tables.scope_key_workspace(ws_id)."""
    return await base.query(
        tables.AUDIT_LOG_TABLE,
        key_condition_expression="scope_key = :s",
        expression_values={":s": scope_key},
        scan_index_forward=False,
        limit=limit,
    )


async def list_by_actor(
    actor_user_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return await base.query(
        tables.AUDIT_LOG_TABLE,
        key_condition_expression="actor_user_id = :a",
        expression_values={":a": actor_user_id},
        index_name=tables.AUDIT_LOG_GSI_ACTOR,
        scan_index_forward=False,
        limit=limit,
    )


# ---------- 写 ----------

async def append(
    *,
    scope_key: str,
    actor_user_id: str,
    actor_role: str,
    operation: str,
    target_type: str,
    target_id: str,
    status: str = "submitted",
    reason: str | None = None,
    aws_request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> dict[str, Any]:
    """append-only; 返回 event_id 给调用方持有, 后续 update_completion 用."""
    event_id = _new_event_id()
    created_at = _now_iso()
    item: dict[str, Any] = {
        "scope_key": scope_key,
        "event_key": tables.event_key(created_at, event_id),
        "event_id": event_id,
        "created_at": created_at,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "operation": operation,
        "target_type": target_type,
        "target_id": target_id,
        "status": status,
        "expire_at": _expire_at(ttl_days),
    }
    if reason:
        item["reason"] = reason
    if aws_request_id:
        item["aws_request_id"] = aws_request_id
    if metadata:
        item["metadata"] = metadata
    await base.put_item(tables.AUDIT_LOG_TABLE, item, ensure_new=True)
    return item


async def update_completion(
    *,
    scope_key: str,
    event_key: str,
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    """异步操作完成时回填 status + completed_at + error_message."""
    sets: list[str] = ["#s = :s", "completed_at = :c"]
    names: dict[str, str] = {"#s": "status"}
    values: dict[str, Any] = {":s": status, ":c": _now_iso()}
    if error_message:
        sets.append("error_message = :em")
        values[":em"] = error_message
    return await base.update_item(
        tables.AUDIT_LOG_TABLE,
        {"scope_key": scope_key, "event_key": event_key},
        update_expression="SET " + ", ".join(sets),
        expression_values=values,
        expression_names=names,
    )
