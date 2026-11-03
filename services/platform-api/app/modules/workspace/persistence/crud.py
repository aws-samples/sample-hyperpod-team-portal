"""Workspace + Membership CRUD (DDB-only).

历史: SQLAlchemy 跨 workspace + user_workspace_role 表的复合查询.
切 DDB 后, 真实实现搬到 ``app.repositories.workspaces`` +
``app.repositories.workspace_members`` + ``app.adapters.aws.compute_quota``.

本文件保留同名函数, ``db`` 参数仍存在但被忽略 (router/orchestration 还在传).
返回值从 ORM 改为 dict; 通过 ``id`` alias 兼容.
"""

from __future__ import annotations

from typing import Any

from app.adapters.aws import compute_quota
from app.adapters.ddb import base
from app.repositories import (
    workspace_members as wm_repo,
)
from app.repositories import (
    workspaces as ws_repo,
)


def _coerce(v: Any) -> str:
    return str(v) if v is not None else ""


def _alias_id(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """workspace_id → id alias (兼容老 ORM 调用 ws.id).

    namespace / name 真值存在 metadata_json (CreateComputeQuota 自动派生的 K8s ns
    + 团队 name 都写在 metadata 里), 顶层是 alias. 顶层缺失时回填 metadata_json.
    """
    if item is not None:
        if "id" not in item and "workspace_id" in item:
            item["id"] = item["workspace_id"]
        meta = item.get("metadata_json") or {}
        # 兼容 owner_user_id / status / name / namespace / cluster_id
        item.setdefault("status", "active")
        item.setdefault(
            "name",
            meta.get("name") or item.get("display_name") or item.get("workspace_id"),
        )
        item.setdefault("namespace", meta.get("namespace") or "")
        item.setdefault("cluster_id", item.get("cluster_arn"))
        item.setdefault("metadata_json", {})
        item.setdefault("description", None)
        item.setdefault(
            "sagemaker_compute_quota_id", item.get("compute_quota_id")
        )
        item.setdefault("sagemaker_compute_quota_arn", None)
    return item


# ===== Workspace =====

async def get_workspace(db: Any, ws_id: Any) -> dict[str, Any] | None:
    del db
    item = await ws_repo.get_workspace(_coerce(ws_id))
    return _alias_id(item)


async def get_workspace_by_name(
    db: Any, cluster_id: Any, name: str
) -> dict[str, Any] | None:
    """name 在 DDB 里没单独索引, scan 全表 + Python 过滤 (规模 ≤30)."""
    del db, cluster_id
    items = await ws_repo.list_all_workspaces()
    for it in items:
        if it.get("display_name") == name or it.get("name") == name:
            return _alias_id(it)
    return None


async def get_workspace_by_namespace(
    db: Any, cluster_id: Any, namespace: str
) -> dict[str, Any] | None:
    del db, cluster_id
    items = await ws_repo.list_all_workspaces()
    for it in items:
        meta = it.get("metadata_json") or {}
        if meta.get("namespace") == namespace:
            return _alias_id(it)
    return None


async def list_workspaces(
    db: Any,
    cluster_id: Any | None = None,
    user_id: Any | None = None,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """合并 owner ws + member ws (按 user_id 过滤时), 否则全部 ws.

    DDB 实现:
        1. user_id 提供时: ws_repo.list_workspaces_by_owner(user_id) +
           wm_repo.list_workspaces_of_user(user_id) → BatchGetItem 取详情
        2. user_id 未提供: ws_repo.list_all_workspaces (规模 ≤30)
    """
    del db
    if user_id is not None:
        uid = _coerce(user_id)
        owner_ws = await ws_repo.list_workspaces_by_owner(uid)
        member_links = await wm_repo.list_workspaces_of_user(uid)
        member_ws_ids = [
            m["workspace_id"] for m in member_links if m.get("workspace_id")
        ]
        owner_ids = {w["workspace_id"] for w in owner_ws}
        extra_ids = [w for w in member_ws_ids if w not in owner_ids]
        member_ws: list[dict[str, Any]] = []
        if extra_ids:
            member_ws = await ws_repo.list_workspaces_by_ids(extra_ids)
        items = list(owner_ws) + list(member_ws)
    else:
        items = await ws_repo.list_all_workspaces()

    # cluster_id / status 过滤 (Python 侧)
    out: list[dict[str, Any]] = []
    for it in items:
        if cluster_id is not None and it.get("cluster_arn") != str(cluster_id):
            # M1 简化: cluster_id 字段不在 DDB; 不严格过滤
            pass
        if status_filter and (it.get("status") or "active") != status_filter:
            continue
        out.append(_alias_id(it) or it)
    out.sort(key=lambda w: w.get("created_at", ""))
    return out


async def create_workspace(
    db: Any,
    *,
    cluster_id: Any,
    name: str,
    display_name: str,
    namespace: str,
    owner_user_id: Any,
    description: str | None = None,
) -> dict[str, Any]:
    """DDB only — 不调 AWS. orchestration 负责先建 AWS ComputeQuota."""
    del db
    metadata = {"namespace": namespace, "name": name}
    item = await ws_repo.create_workspace(
        cluster_arn=str(cluster_id),
        display_name=display_name,
        owner_user_id=_coerce(owner_user_id),
        description=description,
        metadata=metadata,
    )
    return _alias_id(item) or item


async def update_workspace(
    db: Any,
    ws: dict[str, Any],
    *,
    display_name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    del db
    ws_id = _coerce(ws.get("workspace_id") or ws.get("id"))
    updated = await ws_repo.update_workspace(
        ws_id, display_name=display_name, description=description
    )
    ws.update(updated)
    return _alias_id(ws) or ws


async def delete_workspace(db: Any, ws: dict[str, Any]) -> None:
    """硬删 DDB 行 + 级联清成员 (AWS ComputeQuota 由 orchestration 删)."""
    del db
    ws_id = _coerce(ws.get("workspace_id") or ws.get("id"))
    members = await wm_repo.list_members_of_workspace(ws_id)
    for m in members:
        await wm_repo.remove_member(ws_id, m.get("username") or m.get("user_id"))
    await ws_repo.delete_workspace(ws_id)


async def count_members(db: Any, ws_id: Any) -> int:
    """成员数 (无 owner 概念, 直接 count)."""
    del db
    return await wm_repo.count_members(_coerce(ws_id))


# ===== Membership =====

def _alias_membership(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if m is not None:
        m.setdefault("invited_by", None)
    return m


async def get_membership(
    db: Any, ws_id: Any, user_id: Any
) -> dict[str, Any] | None:
    """user_id 参数语义 = IdC username (兼容老命名)."""
    del db
    return _alias_membership(
        await wm_repo.get_member(_coerce(ws_id), _coerce(user_id))
    )


async def list_memberships(db: Any, ws_id: Any) -> list[dict[str, Any]]:
    del db
    items = await wm_repo.list_members_of_workspace(_coerce(ws_id))
    items.sort(key=lambda m: m.get("joined_at", ""))
    for m in items:
        _alias_membership(m)
    return items


async def add_membership(
    db: Any,
    *,
    ws_id: Any,
    user_id: Any,
    role: str,
    email: str | None = None,
    display_name: str | None = None,
    invited_by: Any | None = None,
) -> dict[str, Any]:
    """ON CONFLICT DO NOTHING — 复合主键重复不报错.

    user_id 参数语义 = IdC username (兼容老命名, 实际写入字段是 username).

    底层 add_member 用 transaction (新增 member 行 + Workspaces.member_count +1 atomic),
    成员已存在会抛 ItemAlreadyExists; 这里 swallow 后返回已有成员 dict, 保持
    原 "ON CONFLICT DO NOTHING" 语义.
    """
    del db
    workspace_id = _coerce(ws_id)
    username = _coerce(user_id)
    try:
        item = await wm_repo.add_member(
            workspace_id=workspace_id,
            username=username,
            role=role,
            email=email,
            display_name=display_name,
            invited_by=_coerce(invited_by) if invited_by else None,
        )
        return _alias_membership(item) or item
    except base.ItemAlreadyExists:
        # 成员已存在 (或 ws 不存在). 拉一下成员记录返回; 拉不到说明真的是 ws 问题, 抛.
        existing = await wm_repo.get_member(workspace_id, username)
        if existing is None:
            raise
        return _alias_membership(existing) or existing


async def update_membership_role(
    db: Any, membership: dict[str, Any], role: str
) -> dict[str, Any]:
    del db
    username = membership.get("username") or membership.get("user_id")
    updated = await wm_repo.update_member_role(
        membership["workspace_id"], username, role
    )
    membership.update(updated)
    return _alias_membership(membership) or membership


async def delete_membership(db: Any, membership: dict[str, Any]) -> None:
    del db
    username = membership.get("username") or membership.get("user_id")
    await wm_repo.remove_member(membership["workspace_id"], username)


# Re-export: AWS ComputeQuota helpers (orchestration 用)
__all__ = [
    "_alias_id",
    "_alias_membership",
    "add_membership",
    "compute_quota",  # AWS adapter 透传
    "count_members",
    "create_workspace",
    "delete_membership",
    "delete_workspace",
    "get_membership",
    "get_workspace",
    "get_workspace_by_name",
    "get_workspace_by_namespace",
    "list_memberships",
    "list_workspaces",
    "update_membership_role",
    "update_workspace",
]
