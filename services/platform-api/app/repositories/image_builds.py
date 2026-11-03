"""ImageBuilds Repository — 镜像构建任务/历史 (CodeBuild).

主键: PK=workspace_id, SK="build#<build_id>"。
字段: status / dockerfile / target_repo / target_tag / target_uri / uses /
compute_type / codebuild_id / logs_url / registered_image_id / creator_username /
created_at / updated_at。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def get(workspace_id: str, sort_key: str) -> dict[str, Any] | None:
    return await base.get_item(
        tables.IMAGE_BUILDS_TABLE,
        {"workspace_id": workspace_id, "sort_key": sort_key},
    )


async def list_all(workspace_id: str) -> list[dict[str, Any]]:
    return await base.query(
        tables.IMAGE_BUILDS_TABLE,
        key_condition_expression="workspace_id = :w AND begins_with(sort_key, :p)",
        expression_values={":w": workspace_id, ":p": tables.image_build_prefix()},
    )


async def put(
    *, workspace_id: str, sort_key: str, item_fields: dict[str, Any]
) -> dict[str, Any]:
    """写入 (upsert)。created_at 初次写 now, 已存保留; updated_at 每次刷新。"""
    now = _now_iso()
    existing = await get(workspace_id, sort_key)
    created_at = (existing or {}).get("created_at") or now
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "sort_key": sort_key,
        "created_at": created_at,
        "updated_at": now,
        **item_fields,
    }
    await base.put_item(tables.IMAGE_BUILDS_TABLE, item, ensure_new=False)
    return item
