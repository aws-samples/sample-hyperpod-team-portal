"""MountPermissions Repository — 成员级 FSx 挂载授权.

PK=workspace_id, SK="MOUNT#<mount_id>#USER#<username>".
GSI username-index (PK=username, SK=workspace_id): 开发机创建查"我的权限".

授权记录字段:
    workspace_id, perm_key, mount_id, mount_path, gid (N),
    username, access ("ro"|"rw"), pvc_name_rw, pvc_name_ro,
    granted_by, granted_at
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables

VALID_ACCESS = {"ro", "rw"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------- 写 ----------

async def grant(
    *,
    workspace_id: str,
    mount_id: str,
    username: str,
    access: str,
    mount_path: str,
    gid: int,
    pvc_name_rw: str,
    pvc_name_ro: str,
    granted_by: str,
) -> dict[str, Any]:
    """授权 (覆盖写: access 变更直接 put 覆盖)."""
    if access not in VALID_ACCESS:
        raise ValueError(f"access must be one of {VALID_ACCESS}, got {access}")
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "perm_key": tables.mount_perm_key(mount_id, username),
        "mount_id": mount_id,
        "mount_path": mount_path,
        "gid": gid,
        "username": username,
        "access": access,
        "pvc_name_rw": pvc_name_rw,
        "pvc_name_ro": pvc_name_ro,
        "granted_by": granted_by,
        "granted_at": _now_iso(),
    }
    await base.put_item(tables.MOUNT_PERMISSIONS_TABLE, item, ensure_new=False)
    return item


async def revoke(workspace_id: str, mount_id: str, username: str) -> None:
    """撤销单条授权."""
    await base.delete_item(
        tables.MOUNT_PERMISSIONS_TABLE,
        {
            "workspace_id": workspace_id,
            "perm_key": tables.mount_perm_key(mount_id, username),
        },
        require_exists=False,
    )


async def delete_by_mount(workspace_id: str, mount_id: str) -> int:
    """删挂载级联: 删该挂载所有授权记录. 返删除条数."""
    rows = await list_by_mount(workspace_id, mount_id)
    for r in rows:
        await base.delete_item(
            tables.MOUNT_PERMISSIONS_TABLE,
            {"workspace_id": workspace_id, "perm_key": r["perm_key"]},
            require_exists=False,
        )
    return len(rows)


async def delete_by_user_in_ws(workspace_id: str, username: str) -> int:
    """删成员级联: 删该用户在该 ws 的所有授权记录. 返删除条数."""
    rows = await list_by_user_in_ws(workspace_id, username)
    for r in rows:
        await base.delete_item(
            tables.MOUNT_PERMISSIONS_TABLE,
            {"workspace_id": workspace_id, "perm_key": r["perm_key"]},
            require_exists=False,
        )
    return len(rows)


# ---------- 读 ----------

async def list_by_mount(
    workspace_id: str, mount_id: str
) -> list[dict[str, Any]]:
    """列某挂载的所有授权人 (授权 UI + 级联删用)."""
    return await base.query(
        tables.MOUNT_PERMISSIONS_TABLE,
        key_condition_expression="workspace_id = :w AND begins_with(perm_key, :p)",
        expression_values={
            ":w": workspace_id,
            ":p": tables.mount_perm_prefix(mount_id),
        },
    )


async def list_by_user(username: str) -> list[dict[str, Any]]:
    """列某用户在所有 ws 的授权记录 (GSI username-index)."""
    return await base.query(
        tables.MOUNT_PERMISSIONS_TABLE,
        key_condition_expression="username = :u",
        expression_values={":u": username},
        index_name=tables.MOUNT_PERMISSIONS_GSI_USER,
    )


async def list_by_user_in_ws(
    workspace_id: str, username: str
) -> list[dict[str, Any]]:
    """列某用户在指定 ws 的授权记录 (开发机创建列可选挂载 + 删成员级联)."""
    return await base.query(
        tables.MOUNT_PERMISSIONS_TABLE,
        key_condition_expression="username = :u AND workspace_id = :w",
        expression_values={":u": username, ":w": workspace_id},
        index_name=tables.MOUNT_PERMISSIONS_GSI_USER,
    )
