"""ResourceShares Repository — 开发机/训练资源分享 (creator → 同 ws 指定成员).

PK=workspace_id, SK="SHARE#<res_type>#<res_id>#USER#<target_username>".
GSI target-username-index (PK=target_username, SK=workspace_id): 反查"分享给我的".

记录字段:
    workspace_id, share_key, res_type ("dev"|"train"), res_id,
    target_username, shared_by, shared_at
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def grant(
    *,
    workspace_id: str,
    res_type: str,
    res_id: str,
    target_username: str,
    shared_by: str,
) -> dict[str, Any]:
    """分享 (覆盖写: 重复分享同一人 → 幂等更新 shared_at)."""
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "share_key": tables.share_key(res_type, res_id, target_username),
        "res_type": res_type,
        "res_id": res_id,
        "target_username": target_username,
        "shared_by": shared_by,
        "shared_at": _now_iso(),
    }
    await base.put_item(tables.RESOURCE_SHARES_TABLE, item, ensure_new=False)
    return item


async def revoke(
    workspace_id: str, res_type: str, res_id: str, target_username: str
) -> None:
    """取消单个分享."""
    await base.delete_item(
        tables.RESOURCE_SHARES_TABLE,
        {
            "workspace_id": workspace_id,
            "share_key": tables.share_key(res_type, res_id, target_username),
        },
        require_exists=False,
    )


async def list_by_resource(
    workspace_id: str, res_type: str, res_id: str
) -> list[dict[str, Any]]:
    """列某资源被分享给谁 (分享管理 UI + 级联删)."""
    return await base.query(
        tables.RESOURCE_SHARES_TABLE,
        key_condition_expression="workspace_id = :w AND begins_with(share_key, :p)",
        expression_values={
            ":w": workspace_id,
            ":p": tables.share_prefix(res_type, res_id),
        },
    )


async def list_by_target_user(
    target_username: str, workspace_id: str | None = None
) -> list[dict[str, Any]]:
    """反查某用户"分享给我的" (GSI). 传 workspace_id 则限定该 ws."""
    if workspace_id is not None:
        return await base.query(
            tables.RESOURCE_SHARES_TABLE,
            key_condition_expression="target_username = :u AND workspace_id = :w",
            expression_values={":u": target_username, ":w": workspace_id},
            index_name=tables.RESOURCE_SHARES_GSI_USER,
        )
    return await base.query(
        tables.RESOURCE_SHARES_TABLE,
        key_condition_expression="target_username = :u",
        expression_values={":u": target_username},
        index_name=tables.RESOURCE_SHARES_GSI_USER,
    )


async def delete_by_resource(
    workspace_id: str, res_type: str, res_id: str
) -> int:
    """删资源级联: 删该资源所有分享记录. 返删除条数."""
    rows = await list_by_resource(workspace_id, res_type, res_id)
    for r in rows:
        await base.delete_item(
            tables.RESOURCE_SHARES_TABLE,
            {"workspace_id": workspace_id, "share_key": r["share_key"]},
            require_exists=False,
        )
    return len(rows)
