"""资源模板编排: 权限校验 + seed 默认 + CRUD (统一一套, 不分类型).

2026-06-14 确定: 开发机/训练/推理 共用一套模板, 仅 admin 管。
- 增删改 → 仅 ws admin (WorkspaceMembers.role == 'admin') 或 平台超管。
- 读 → 全 ws 成员可见 (用户创建任务时只能选, 不能改/自建)。
- 字段统一单值 gpu/cpu_cores/mem_gib (K8s req=lim)。
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables
from app.core.i18n import t
from app.modules.resource_templates.api.schemas import (
    TemplateCreate,
    TemplateResource,
    TemplateUpdate,
)
from app.modules.workspace.persistence import crud as ws_crud
from app.repositories import resource_templates as repo


# ---------- 预置默认模板 (统一一套, 单位: cpu 核 / 内存 GiB; req=lim) ----------
def _seed_defaults() -> list[dict[str, Any]]:
    """内置预置模板。名称/描述在写入时按当前请求语言生成 (落库后不随语言切换变化)。"""
    return [
        {
            "name": t("resource_templates.seed.small.name"),
            "description": t("resource_templates.seed.small.description"),
            "gpu": 1, "cpu_cores": 8, "mem_gib": 32,
        },
        {
            "name": t("resource_templates.seed.medium.name"),
            "description": t("resource_templates.seed.medium.description"),
            "gpu": 1, "cpu_cores": 16, "mem_gib": 48,
        },
        {
            "name": t("resource_templates.seed.large.name"),
            "description": t("resource_templates.seed.large.description"),
            "gpu": 2, "cpu_cores": 32, "mem_gib": 96,
        },
        {
            "name": t("resource_templates.seed.xlarge.name"),
            "description": t("resource_templates.seed.xlarge.description"),
            "gpu": 4, "cpu_cores": 48, "mem_gib": 192,
        },
    ]


def _username(user: dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("username") or user.get("id"))


def _decimal_to_number(obj: Any) -> Any:
    """DDB 返回的 Decimal 转回 int/float (否则 JSON 序列化成字符串)。"""
    from decimal import Decimal

    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_number(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_number(v) for v in obj]
    return obj


async def _is_ws_admin(ws_id: str, user: dict[str, Any]) -> bool:
    """ws admin = 平台超管 或 该 ws 的 member.role == 'admin' (复用 core.security)。"""
    from app.core.security import is_ws_admin
    return await is_ws_admin(ws_id, user)


async def _require_ws_member(ws_id: str, user: dict[str, Any]) -> None:
    """校验 user 是该 ws 成员 (平台超管豁免)。非成员抛 403, 防跨 ws 越权读写。"""
    if user.get("is_admin"):
        return
    m = await ws_crud.get_membership(None, ws_id, _username(user))
    if not m:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("resource_templates.not_ws_member"),
        )


async def _require_ws_admin(ws_id: str, user: dict[str, Any]) -> None:
    """增删改模板需 ws admin (API 层安全闸: 非 admin 一律 403)。"""
    if not await _is_ws_admin(ws_id, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, t("resource_templates.admin_only")
        )


def _validate_resource(resource: dict[str, Any]) -> dict[str, Any]:
    """统一校验 resource (gpu/cpu_cores/mem_gib 单值)。

    Pydantic 在此卡边界 (gpu 0-8 / cpu 0-128 核 / mem 0-1024 GiB), API 层安全闸。
    """
    return TemplateResource(**resource).model_dump()


def _to_item(sort_key: str, row: dict[str, Any]) -> dict[str, Any]:
    """DDB row → TemplateItem dict (template_id 从 SK 末段取)。"""
    template_id = sort_key.rsplit("#", 1)[-1]
    return {
        "template_id": template_id,
        "name": row.get("name"),
        "description": row.get("description"),
        # DDB 返回 Decimal, 转回 int/float (否则 JSON 序列化成字符串)
        "resource": _decimal_to_number(row.get("resource") or {}),
        "creator_username": row.get("creator_username") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


# ---------- seed ----------

async def ensure_seeded(workspace_id: str) -> None:
    """懒初始化: 该 ws 无任何模板时, 写入内置预置 (统一一套)。"""
    existing = await repo.list_all(workspace_id)
    if existing:
        return
    for spec in _seed_defaults():
        tid = _uuid.uuid4().hex[:8]
        resource = {k: v for k, v in spec.items() if k not in ("name", "description")}
        await repo.put(
            workspace_id=workspace_id,
            sort_key=tables.res_tpl_key(tid),
            item_fields={
                "name": spec["name"],
                "description": spec.get("description"),
                "resource": resource,
                "creator_username": "system",
            },
        )


# ---------- 读 ----------

async def list_templates(
    workspace_id: str, user: dict[str, Any]
) -> list[dict[str, Any]]:
    """该 ws 全部模板 (统一一套, 全员可见)。"""
    await _require_ws_member(workspace_id, user)
    await ensure_seeded(workspace_id)
    rows = await repo.list_all(workspace_id)
    return [_to_item(r["sort_key"], r) for r in rows]


# ---------- 写 (仅 admin) ----------

async def create_template(
    workspace_id: str, payload: TemplateCreate, user: dict[str, Any]
) -> dict[str, Any]:
    await _require_ws_member(workspace_id, user)
    await _require_ws_admin(workspace_id, user)
    resource = _validate_resource(payload.resource)
    tid = _uuid.uuid4().hex[:8]
    sk = tables.res_tpl_key(tid)
    row = await repo.put(
        workspace_id=workspace_id,
        sort_key=sk,
        item_fields={
            "name": payload.name,
            "description": payload.description,
            "resource": resource,
            "creator_username": _username(user),
        },
    )
    return _to_item(sk, row)


async def update_template(
    workspace_id: str,
    template_id: str,
    payload: TemplateUpdate,
    user: dict[str, Any],
) -> dict[str, Any]:
    await _require_ws_member(workspace_id, user)
    await _require_ws_admin(workspace_id, user)
    sk = tables.res_tpl_key(template_id)
    existing = await repo.get(workspace_id, sk)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("resource_templates.not_found"))
    fields = dict(existing)
    for k in ("workspace_id", "sort_key", "created_at", "updated_at"):
        fields.pop(k, None)
    if payload.name is not None:
        fields["name"] = payload.name
    if payload.description is not None:
        fields["description"] = payload.description
    if payload.resource is not None:
        fields["resource"] = _validate_resource(payload.resource)
    row = await repo.put(workspace_id=workspace_id, sort_key=sk, item_fields=fields)
    return _to_item(sk, row)


async def delete_template(
    workspace_id: str,
    template_id: str,
    user: dict[str, Any],
) -> None:
    await _require_ws_member(workspace_id, user)
    await _require_ws_admin(workspace_id, user)
    await repo.delete(workspace_id, tables.res_tpl_key(template_id))
