"""列表可见性辅助: 反查"分享给我的" res_id 集合, 供 dev/train crud 并入列表。"""

from __future__ import annotations

from app.repositories import resource_shares as shares_repo


async def shared_res_ids(
    workspace_id: str, username: str, res_type: str
) -> set[str]:
    """返回"分享给该用户的、指定类型的" res_id 集合 (限本 ws)。"""
    rows = await shares_repo.list_by_target_user(username, workspace_id=workspace_id)
    return {
        r.get("res_id")
        for r in rows
        if r.get("res_type") == res_type and r.get("res_id")
    }
