"""Workspace 详情 / 成员列表 response 组装.

输入是 dict (DDB items + AWS-derived ws), 输出 Pydantic schema.

PR feat/no-users-table-username-as-id, 2026-05-20:
    - ws 无 owner 概念, builder 不再反查 user 拿 owner email/name
      WorkspaceDetail 的 owner_* 字段都返空字符串 (兼容前端 TS 不破)
    - 成员显示 email/display_name 直接从 WorkspaceMembers 行的冗余字段读
      (写入时由 add_member 拍快照, 改名后陈旧但语义清晰)
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.modules.workspace.api.schemas import MemberResponse, WorkspaceDetail
from app.modules.workspace.persistence import crud


def _cluster_tag_from_arn(cluster_id: str) -> str:
    """cluster_id 是 SageMaker HyperPod cluster ARN, tag = ARN 最后一段.

    例: arn:aws:sagemaker:ap-south-1:123456789012:cluster/hp-fsx-demo
        → hp-fsx-demo
    若 cluster_id 不像 ARN, 直接返回原值 (兼容老数据).
    """
    if not cluster_id:
        return "unknown"
    return cluster_id.rsplit("/", 1)[-1]


async def build_workspace_detail(
    db: Any, ws: dict[str, Any]
) -> WorkspaceDetail:
    """组 WorkspaceDetail. 0 跨表查询: cluster_tag 从 ARN 切, member_count 直接读 ws 冗余字段.

    PR feat/no-users-table-username-as-id 起 ws 无 owner, 不再调 users_repo.
    """
    del db
    cluster_id = ws.get("cluster_id") or ws.get("cluster_arn") or ""
    ws_id = ws.get("workspace_id") or ws.get("id")
    # member_count 冗余在 Workspaces 表 (add_member/remove_member 时原子 ±1 维护).
    # 老 ws 缺这个字段时退化为 0, 走 backfill 脚本补.
    member_cnt = int(ws.get("member_count") or 0)

    metadata = ws.get("metadata_json") or {}
    # name 顶层字段 (新建 ws 时由 create_workspace 写入). 老 ws 缺时退化到 metadata.
    # 注意: 不再 fallback 到 display_name, 因为 display_name 是 friendly 名,
    # 跟 slug 语义完全不同.
    name = ws.get("name") or metadata.get("name") or ""
    namespace = ws.get("namespace") or metadata.get("namespace") or ""

    return WorkspaceDetail(
        id=str(ws_id) if ws_id else "",
        cluster_id=str(cluster_id),
        cluster_tag=_cluster_tag_from_arn(cluster_id),
        name=name,
        display_name=ws.get("display_name") or "",
        namespace=namespace,
        description=ws.get("description"),
        # owner_* 字段保留兼容前端 TS, 但永远空 (PR feat/no-users-table-username-as-id)
        owner_user_id="",
        owner_display_name="",
        owner_email="",
        status=ws.get("status") or "active",
        member_count=member_cnt,
        quota_summary=None,
        sagemaker_compute_quota_id=ws.get("sagemaker_compute_quota_id")
        or ws.get("compute_quota_id"),
        sagemaker_compute_quota_arn=ws.get("sagemaker_compute_quota_arn"),
        metadata_json=metadata,
        created_at=ws.get("created_at") or "",
        updated_at=ws.get("updated_at") or "",
    )


async def list_members_flow(
    db: Any, ws_id: Any
) -> list[MemberResponse]:
    """列出 workspace 成员.

    PR feat/no-users-table-username-as-id 起:
        - 不再合成 'owner' 行 (ws 无 owner 概念)
        - 直接读 WorkspaceMembers 行的冗余 email / display_name 字段
        - user_id 字段值 = IdC username
    """
    del db
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )

    rows = await crud.list_memberships(None, ws_id)

    members: list[MemberResponse] = []
    for uwr in rows:
        members.append(
            MemberResponse(
                user_id=str(uwr.get("username") or uwr.get("user_id") or ""),
                email=uwr.get("email") or "",
                display_name=uwr.get("display_name") or "",
                role=uwr.get("role"),  # type: ignore[arg-type]
                joined_at=uwr.get("joined_at") or "",
            )
        )
    return members
