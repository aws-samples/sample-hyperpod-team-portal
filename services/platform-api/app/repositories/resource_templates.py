"""ResourceTemplates Repository — 资源模板 (开发机/训练/推理 统一一套, 不分类型).

2026-06-14 确定: 三类共用一套,
仅 admin 管 (无 type / 无 custom), 用户只能选不能改/自建。

主键:
    PK = workspace_id
    SK = "tpl#<template_id>"   (全是 admin 统一档, 全 ws 可见)

字段: gpu/cpu_cores/mem_gib (单值, req=lim) + name/description/creator_username/
created_at/updated_at。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.adapters.ddb import base, tables


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _floats_to_decimal(obj: Any) -> Any:
    """递归把 float 转 Decimal (DDB 不接受 Python float)。

    资源字段 cpu_cores/mem_gib 是 float (核/GiB 可小数), boto3 高层 put_item 拒 float,
    要 Decimal。int / str / 其他类型原样。
    """
    if isinstance(obj, float):
        # 经字符串转, 避免二进制浮点误差 (4.0 → Decimal('4.0') 而非 4.00000…)
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj


# ---------- 读 ----------

async def get(
    workspace_id: str, sort_key: str
) -> dict[str, Any] | None:
    """按完整 SK 取单条 (SK 由 caller 用 tables.res_tpl_key_* 构造)。"""
    return await base.get_item(
        tables.RESOURCE_TEMPLATES_TABLE,
        {"workspace_id": workspace_id, "sort_key": sort_key},
    )


async def list_all(workspace_id: str) -> list[dict[str, Any]]:
    """该 ws 全部模板 (统一一套, 全 ws 可见; 仅 admin 管)。"""
    return await base.query(
        tables.RESOURCE_TEMPLATES_TABLE,
        key_condition_expression=(
            "workspace_id = :w AND begins_with(sort_key, :p)"
        ),
        expression_values={
            ":w": workspace_id,
            ":p": tables.res_tpl_prefix(),
        },
    )


# ---------- 写 ----------

async def put(
    *,
    workspace_id: str,
    sort_key: str,
    item_fields: dict[str, Any],
) -> dict[str, Any]:
    """写入 (upsert)。item_fields = 资源字段 + 公共字段 (name/type/scope/...)。

    created_at 初次写 now, 已存保留旧值; updated_at 每次刷新。
    """
    existing = await get(workspace_id, sort_key)
    now = _now_iso()
    created_at = (existing or {}).get("created_at") or now
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "sort_key": sort_key,
        "created_at": created_at,
        "updated_at": now,
        **item_fields,
    }
    # DDB 不接受 Python float, 递归转 Decimal (cpu_cores/mem_gib 可小数)
    await base.put_item(
        tables.RESOURCE_TEMPLATES_TABLE, _floats_to_decimal(item), ensure_new=False
    )
    return item


async def delete(workspace_id: str, sort_key: str) -> None:
    await base.delete_item(
        tables.RESOURCE_TEMPLATES_TABLE,
        {"workspace_id": workspace_id, "sort_key": sort_key},
        require_exists=False,
    )
