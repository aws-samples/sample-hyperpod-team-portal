"""资源分享 API (开发机/训练)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from app.core.security import assert_ws_member, get_current_user
from app.modules.sharing import orchestration as orch
from app.modules.sharing.api.schemas import ShareBody, ShareItem

router = APIRouter(tags=["sharing"])


def _to_item(row: dict[str, Any]) -> ShareItem:
    return ShareItem(
        res_type=row.get("res_type") or "",
        res_id=row.get("res_id") or "",
        target_username=row.get("target_username") or "",
        shared_by=row.get("shared_by") or "",
        shared_at=row.get("shared_at") or "",
    )


@router.post(
    "/workspaces/{ws_id}/shares",
    response_model=list[ShareItem],
    summary="批量分享资源给同 ws 成员",
    description=(
        "把某个资源只读分享给本 ws 内一批目标用户.\n\n"
        "- `res_type` **只支持 {`dev`, `train`}** (推理不支持分享); 传其他值 422\n"
        "- `target_usernames` 必须都是本 ws 成员, 且不能是自己 (自己即 creator); 违反返 **400**\n"
        "- 分享后目标用户在自己列表 / 详情页可只读查看, 不能改 / 停 / 删\n"
        "- **幂等**: 重复分享同一人是覆盖写 (刷新 `shared_at`), 仍出现在返回里\n"
        "- **非原子**: 逐个目标写入, 中途某目标校验失败 (400) 时前面已写入的分享保留\n\n"
        "**权限**: 资源所属 ws 的成员 **且是资源创建者本人** (ws 管理员也不行)."
    ),
    responses={
        400: {"description": "目标用户不是本 ws 成员; 或分享给自己"},
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员; 或非资源创建者本人"},
        404: {"description": "资源不存在或已软删"},
        422: {"description": "res_type 不在 {dev, train} / res_id 空 / target_usernames 空"},
    },
)
async def create_shares(
    ws_id: str,
    body: ShareBody,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[ShareItem]:
    await assert_ws_member(ws_id, current_user)
    rows = await orch.share_resource(
        ws_id, body.res_type, body.res_id, body.target_usernames, current_user
    )
    return [_to_item(r) for r in rows]


@router.get(
    "/workspaces/{ws_id}/shares/{res_type}/{res_id}",
    response_model=list[ShareItem],
    summary="列某资源当前的分享名单",
    description=(
        "返 `(res_type, res_id)` 已被分享给的目标用户列表 (含分享人 / 分享时间), "
        "用于详情页 **管理分享** 抽屉展示已加名单.\n\n"
        "- `res_type` 是路径参数, **只支持 {`dev`, `train`}**, 其他值返 400\n\n"
        "**权限**: ws 成员 **且是资源创建者本人**."
    ),
    responses={
        400: {"description": "res_type 不在 {dev, train}"},
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员; 或非资源创建者本人"},
        404: {"description": "资源不存在或已软删"},
    },
)
async def list_resource_shares(
    ws_id: str,
    res_type: str,
    res_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[ShareItem]:
    await assert_ws_member(ws_id, current_user)
    rows = await orch.list_shares(ws_id, res_type, res_id, current_user)
    return [_to_item(r) for r in rows]


@router.delete(
    "/workspaces/{ws_id}/shares/{res_type}/{res_id}/users/{username}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="取消对某用户的分享",
    description=(
        "撤销 `(res_type, res_id)` 对 `username` 的只读分享. 被撤销后目标用户列表 / 详情页立即失去该资源的可见性.\n\n"
        "- `res_type` **只支持 {`dev`, `train`}**, 其他值返 400\n\n"
        "**权限**: ws 成员 **且是资源创建者本人**. **幂等**: 撤销未分享过的目标也返 204."
    ),
    responses={
        400: {"description": "res_type 不在 {dev, train}"},
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员; 或非资源创建者本人"},
        404: {"description": "资源不存在或已软删"},
    },
)
async def delete_share(
    ws_id: str,
    res_type: str,
    res_id: str,
    username: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    await assert_ws_member(ws_id, current_user)
    await orch.unshare_resource(ws_id, res_type, res_id, username, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
