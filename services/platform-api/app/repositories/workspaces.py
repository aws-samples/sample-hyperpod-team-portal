"""Workspace Repository — DDB Workspaces 表.

ComputeQuota 是 name/namespace/status/quota 的 source-of-truth;
DDB 只存 AWS API 没有的业务字段:
    - display_name        (中文友好名)
    - metadata_json       (业务标签)
+ 反向索引必备: compute_quota_id, cluster_arn, created_at

GSI 规划:
    - compute_quota_id-index    AWS quota → ws_id 反查 (sync 路径)

PR feat/no-users-table-username-as-id, 2026-05-20:
    - 删 owner_user_id 字段 + owner-index GSI (ws 无 owner 概念)
    - list_workspaces_by_owner 保留为兼容 stub, 返空 list

跨表查询 (我加入的所有 ws) 走 WorkspaceMembers.username-index → BatchGetItem(Workspaces).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------- 读 ----------

async def get_workspace(workspace_id: str) -> dict[str, Any] | None:
    return await base.get_item(tables.WORKSPACES_TABLE, {"workspace_id": workspace_id})


async def get_workspace_by_compute_quota(compute_quota_id: str) -> dict[str, Any] | None:
    items = await base.query(
        tables.WORKSPACES_TABLE,
        key_condition_expression="compute_quota_id = :q",
        expression_values={":q": compute_quota_id},
        index_name=tables.WORKSPACES_GSI_QUOTA,
        limit=1,
    )
    return items[0] if items else None


async def list_workspaces_by_owner(owner_user_id: str) -> list[dict[str, Any]]:
    """Deprecated stub (PR feat/no-users-table-username-as-id, 2026-05-20).

    ws 无 owner 概念了, owner-index GSI 已删. 返空 list 给老调用方兜底,
    callers 应改用 WorkspaceMembers.username-index 找 "我加入的 ws".
    """
    del owner_user_id
    return []


async def list_workspaces_by_ids(workspace_ids: list[str]) -> list[dict[str, Any]]:
    """BatchGet — 给 WorkspaceMembers 反查后批量取详情用."""
    keys = [{"workspace_id": wid} for wid in workspace_ids]
    return await base.batch_get_items(tables.WORKSPACES_TABLE, keys)


async def list_all_workspaces() -> list[dict[str, Any]]:
    """全表扫 (规模 ≤30 ws). 管理员视图."""
    return await base.scan_all(tables.WORKSPACES_TABLE)


# ---------- 写 ----------

async def create_workspace(
    *,
    cluster_arn: str,
    name: str,
    display_name: str,
    namespace: str,
    owner_user_id: str = "",  # PR feat/no-users-table-username-as-id: 兼容参数, 不再存
    compute_quota_id: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建 workspace 行.

    name = 用户填的 slug (例: bob-test-2), 顶层字段, 列表展示用.
    namespace = K8s ns, 顶层字段, 列表展示用 (跟 metadata.namespace 冗余).
    display_name = friendly 名 (例: Team - Atlas).

    PR feat/no-users-table-username-as-id, 2026-05-20:
        - owner_user_id 参数保留兼容老 caller, 但**不写入 row** (ws 无 owner 概念)
        - 创建人审计应通过 AuditLog 表 (单独 PR 接通, 这里不动)
    """
    del owner_user_id  # 兼容参数, 不写入
    workspace_id = _new_uuid()
    now = _now_iso()
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "cluster_arn": cluster_arn,
        "name": name,
        "display_name": display_name,
        "namespace": namespace,
        "created_at": now,
        "updated_at": now,
        "metadata_json": metadata or {},
    }
    if compute_quota_id:
        item["compute_quota_id"] = compute_quota_id
    if description:
        item["description"] = description
    await base.put_item(tables.WORKSPACES_TABLE, item, ensure_new=True)
    return item


async def update_workspace(
    workspace_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    compute_quota_id: str | None = None,
) -> dict[str, Any]:
    sets: list[str] = ["updated_at = :u"]
    values: dict[str, Any] = {":u": _now_iso()}
    if display_name is not None:
        sets.append("display_name = :dn")
        values[":dn"] = display_name
    if description is not None:
        sets.append("description = :ds")
        values[":ds"] = description
    if metadata is not None:
        sets.append("metadata_json = :m")
        values[":m"] = metadata
    if compute_quota_id is not None:
        sets.append("compute_quota_id = :q")
        values[":q"] = compute_quota_id
    return await base.update_item(
        tables.WORKSPACES_TABLE,
        {"workspace_id": workspace_id},
        update_expression="SET " + ", ".join(sets),
        expression_values=values,
    )


async def delete_workspace(workspace_id: str) -> None:
    await base.delete_item(
        tables.WORKSPACES_TABLE, {"workspace_id": workspace_id}, require_exists=False
    )
