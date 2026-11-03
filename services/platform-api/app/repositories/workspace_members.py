"""WorkspaceMembers Repository — DDB WorkspaceMembers 表.

PK=workspace_id, SK=username (= IdC username); 复合主键天然保证 (ws,user) 唯一.
GSI=username-index (PK=username, SK=workspace_id) 反查我加入的所有 ws.

角色两种 (2026-05-21 简化):
    - admin:  workspace 管理员, 能加/减成员, 调队列优先级
    - member: 普通成员, 能创建任务/开发机
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables
from app.adapters.ddb.base import TransactionConflict


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


VALID_ROLES = {"admin", "member"}


# ---------- 读 ----------

async def get_member(workspace_id: str, username: str) -> dict[str, Any] | None:
    return await base.get_item(
        tables.WORKSPACE_MEMBERS_TABLE,
        {"workspace_id": workspace_id, "username": username},
    )


async def list_members_of_workspace(workspace_id: str) -> list[dict[str, Any]]:
    return await base.query(
        tables.WORKSPACE_MEMBERS_TABLE,
        key_condition_expression="workspace_id = :w",
        expression_values={":w": workspace_id},
    )


async def list_workspaces_of_user(username: str) -> list[dict[str, Any]]:
    """返回 [{workspace_id, role, joined_at, ...}], 只含 GSI 投影字段 (= ALL)."""
    return await base.query(
        tables.WORKSPACE_MEMBERS_TABLE,
        key_condition_expression="username = :u",
        expression_values={":u": username},
        index_name=tables.WORKSPACE_MEMBERS_GSI_USER,
    )


async def count_members(workspace_id: str) -> int:
    """成员数 (没 owner, 直接 count). 用于一次性 backfill, 热路径不要调."""
    members = await list_members_of_workspace(workspace_id)
    return len(members)


# ---------- 写 ----------

async def add_member(
    *,
    workspace_id: str,
    username: str,
    role: str,
    email: str | None = None,
    display_name: str | None = None,
    invited_by: str | None = None,
) -> dict[str, Any]:
    """加成员 (atomic transaction): 写 member 行 + Workspaces.member_count += 1.

    幂等: 重复加同一 user 时 (member 行已存在) 整个事务回滚, 抛 ItemAlreadyExists,
    调用方可静默 swallow. count 不会被加多.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role}")
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "username": username,
        "role": role,
        "joined_at": _now_iso(),
    }
    if email:
        item["email"] = email
    if display_name:
        item["display_name"] = display_name
    if invited_by:
        item["invited_by"] = invited_by

    # 事务: Put member 行 (条件: member 不存在) + Workspaces.member_count += 1.
    # member_count 字段不存在时 ADD 自动初始化为 0 再 +1.
    ops = [
        base.put_op(
            tables.WORKSPACE_MEMBERS_TABLE,
            item,
            condition_expression="attribute_not_exists(workspace_id) AND attribute_not_exists(username)",
        ),
        base.update_op(
            tables.WORKSPACES_TABLE,
            {"workspace_id": workspace_id},
            update_expression="ADD member_count :one SET updated_at = :u",
            expression_values={":one": 1, ":u": _now_iso()},
            condition_expression="attribute_exists(workspace_id)",
        ),
    ]
    try:
        await base.transact_write(ops)
    except TransactionConflict as e:
        # 任一 condition 失败: member 已存在 或 ws 不存在
        # 调用方需要根据语义判断 — 这里转译成 ItemAlreadyExists (业务侧最常见原因)
        raise base.ItemAlreadyExists(
            f"workspace_member exists or workspace missing: {e}"
        ) from e
    return item


async def update_member_role(
    workspace_id: str, username: str, role: str
) -> dict[str, Any]:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role}")
    return await base.update_item(
        tables.WORKSPACE_MEMBERS_TABLE,
        {"workspace_id": workspace_id, "username": username},
        update_expression="SET #r = :r",
        expression_values={":r": role},
        expression_names={"#r": "role"},
    )


async def remove_member(workspace_id: str, username: str) -> None:
    """删成员 (atomic transaction): 删 member 行 + Workspaces.member_count -= 1.

    幂等: member 不存在时事务回滚, 静默吞掉 (用户已退出, 没什么可做).
    count 不会被减多.
    """
    ops = [
        base.delete_op(
            tables.WORKSPACE_MEMBERS_TABLE,
            {"workspace_id": workspace_id, "username": username},
            condition_expression="attribute_exists(workspace_id) AND attribute_exists(username)",
        ),
        base.update_op(
            tables.WORKSPACES_TABLE,
            {"workspace_id": workspace_id},
            update_expression="ADD member_count :neg_one SET updated_at = :u",
            expression_values={":neg_one": -1, ":u": _now_iso()},
            condition_expression="attribute_exists(workspace_id)",
        ),
    ]
    try:
        await base.transact_write(ops)
    except TransactionConflict:
        # member 行不存在 (重复调用) 或 ws 不存在 — 都视作 noop
        return
