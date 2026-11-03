"""资源分享编排: 校验 + grant/revoke/list.

权限: 仅资源 creator 本人可分享/取消分享 (不含 ws-admin)。
范围: 仅同 ws 成员可被分享。res_type 只支持 dev/train (推理不分享)。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables
from app.core.i18n import t
from app.modules.workspace.persistence import crud as ws_crud
from app.repositories import resource_index as ri_repo
from app.repositories import resource_shares as shares_repo

# res_type → resource_index 的 RESOURCE_TYPE_* (分享支持: dev / train / rayjob)
_VALID_RES_TYPES = {
    tables.RESOURCE_TYPE_DEV,
    tables.RESOURCE_TYPE_TRAIN,
    tables.RESOURCE_TYPE_RAYJOB,
}


def _username(user: dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("username") or user.get("id"))


def _assert_valid_type(res_type: str) -> None:
    if res_type not in _VALID_RES_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t("sharing.res_type_unsupported", supported=sorted(_VALID_RES_TYPES), res_type=res_type),
        )


async def _load_resource_as_creator(
    workspace_id: str, res_type: str, res_id: str, user: dict[str, Any]
) -> dict[str, Any]:
    """校验 res 存在且未软删 (404) + 调用者是 creator (403)。返回该 row。"""
    row = await ri_repo.get_resource(workspace_id, res_type, res_id)
    if row is None or row.get("deleted_at"):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"resource not found: {res_type}#{res_id}"
        )
    if str(row.get("creator_user_id") or "") != _username(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, t("sharing.creator_only")
        )
    return row


async def share_resource(
    workspace_id: str,
    res_type: str,
    res_id: str,
    target_usernames: list[str],
    user: dict[str, Any],
) -> list[dict[str, Any]]:
    _assert_valid_type(res_type)
    await _load_resource_as_creator(workspace_id, res_type, res_id, user)
    caller = _username(user)
    out: list[dict[str, Any]] = []
    for target in target_usernames:
        target = target.strip()
        if not target:
            continue
        # 不能分享给自己 (自己就是 creator, 分享无意义)
        if target == caller:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, t("sharing.cannot_share_with_self")
            )
        # 仅同 ws 成员可被分享
        m = await ws_crud.get_membership(None, workspace_id, target)
        if not m:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                t("sharing.target_not_member", username=target),
            )
        row = await shares_repo.grant(
            workspace_id=workspace_id,
            res_type=res_type,
            res_id=res_id,
            target_username=target,
            shared_by=_username(user),
        )
        out.append(row)
    return out


async def unshare_resource(
    workspace_id: str,
    res_type: str,
    res_id: str,
    target_username: str,
    user: dict[str, Any],
) -> None:
    _assert_valid_type(res_type)
    await _load_resource_as_creator(workspace_id, res_type, res_id, user)
    await shares_repo.revoke(workspace_id, res_type, res_id, target_username)


async def list_shares(
    workspace_id: str, res_type: str, res_id: str, user: dict[str, Any]
) -> list[dict[str, Any]]:
    _assert_valid_type(res_type)
    await _load_resource_as_creator(workspace_id, res_type, res_id, user)
    return await shares_repo.list_by_resource(workspace_id, res_type, res_id)
