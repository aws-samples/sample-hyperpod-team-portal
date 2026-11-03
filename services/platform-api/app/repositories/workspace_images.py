"""WorkspaceImages Repository — 工作空间镜像中心 (引用模型).

注册 = 在 ws 记一条 "ECR 镜像 URI + 适用用途" 引用, 不复制镜像。任何 ws 成员可
注册/删, 全 ws 可见。创建开发机/训练/推理时按用途筛选选用。

主键:
    PK = workspace_id
    SK = "img#<image_id>"

字段: image_uri / display_name / uses(list) / source / creator_username / created_at。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def get(workspace_id: str, sort_key: str) -> dict[str, Any] | None:
    return await base.get_item(
        tables.WORKSPACE_IMAGES_TABLE,
        {"workspace_id": workspace_id, "sort_key": sort_key},
    )


async def list_all(workspace_id: str) -> list[dict[str, Any]]:
    """该 ws 全部注册镜像 (全 ws 可见)。"""
    return await base.query(
        tables.WORKSPACE_IMAGES_TABLE,
        key_condition_expression=(
            "workspace_id = :w AND begins_with(sort_key, :p)"
        ),
        expression_values={
            ":w": workspace_id,
            ":p": tables.ws_image_prefix(),
        },
    )


async def put(
    *,
    workspace_id: str,
    sort_key: str,
    item_fields: dict[str, Any],
) -> dict[str, Any]:
    """写入 (新建)。created_at 初次写 now。"""
    now = _now_iso()
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "sort_key": sort_key,
        "created_at": now,
        **item_fields,
    }
    await base.put_item(tables.WORKSPACE_IMAGES_TABLE, item, ensure_new=False)
    return item


async def delete(workspace_id: str, sort_key: str) -> None:
    await base.delete_item(
        tables.WORKSPACE_IMAGES_TABLE,
        {"workspace_id": workspace_id, "sort_key": sort_key},
        require_exists=False,
    )
