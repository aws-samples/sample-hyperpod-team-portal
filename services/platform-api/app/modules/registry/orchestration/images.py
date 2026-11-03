"""镜像中心编排: 权限校验 + 注册/列/删 (引用模型)。

权限 (2026-07 确定): 任何 ws 成员均可注册/列/删 (镜像是共享协作资源, 门槛低);
非 ws 成员一律 403 (防跨 ws 越权)。不二次校验 ECR (前端已从真实 ECR 列表选)。
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables
from app.core.i18n import t
from app.modules.registry.api.schemas import RegisterImageBody
from app.modules.workspace.persistence import crud as ws_crud
from app.repositories import workspace_images as repo


def _username(user: dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("username") or user.get("id"))


async def _require_ws_member(ws_id: str, user: dict[str, Any]) -> None:
    """校验 user 是该 ws 成员 (平台超管豁免)。非成员抛 403。"""
    if user.get("is_admin"):
        return
    m = await ws_crud.get_membership(None, ws_id, _username(user))
    if not m:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("registry.not_ws_member"),
        )


def _short_name_from_uri(uri: str) -> str:
    """URI 末段 (repo:tag) 作兜底显示名。"""
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


def _to_item(sort_key: str, row: dict[str, Any]) -> dict[str, Any]:
    """DDB row → WorkspaceImageItem dict (image_id 从 SK 末段取)。"""
    image_id = sort_key.rsplit("#", 1)[-1]
    return {
        "id": image_id,
        "image_uri": row.get("image_uri") or "",
        "display_name": row.get("display_name") or "",
        "uses": list(row.get("uses") or []),
        "source": row.get("source") or "ecr-private",
        "creator_username": row.get("creator_username") or "",
        "created_at": row.get("created_at") or "",
    }


# ---------- 读 ----------

async def list_images(
    workspace_id: str, user: dict[str, Any]
) -> list[dict[str, Any]]:
    await _require_ws_member(workspace_id, user)
    rows = await repo.list_all(workspace_id)
    items = [_to_item(r["sort_key"], r) for r in rows]
    # 最近注册的排前
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


# ---------- 写 (任何 ws 成员) ----------

async def register_image(
    workspace_id: str, payload: RegisterImageBody, user: dict[str, Any]
) -> dict[str, Any]:
    await _require_ws_member(workspace_id, user)
    image_id = _uuid.uuid4().hex[:12]
    sk = tables.ws_image_key(image_id)
    row = await repo.put(
        workspace_id=workspace_id,
        sort_key=sk,
        item_fields={
            "image_uri": payload.image_uri.strip(),
            "display_name": (
                payload.display_name.strip()
                or _short_name_from_uri(payload.image_uri.strip())
            ),
            "uses": list(payload.uses),
            "source": payload.source,
            "creator_username": _username(user),
        },
    )
    return _to_item(sk, row)


async def unregister_image(
    workspace_id: str, image_id: str, user: dict[str, Any]
) -> None:
    await _require_ws_member(workspace_id, user)
    await repo.delete(workspace_id, tables.ws_image_key(image_id))


# ---------- 内部 seed (建 ws 时自动灌基础镜像, 无成员校验) ----------

async def seed_images(
    workspace_id: str,
    images: list[tuple[str, str]],
    creator_username: str,
    *,
    uses: list[str] | None = None,
) -> int:
    """建 ws 时把开发机基础镜像自动注册进镜像中心 (best-effort, 不校验成员)。

    images: (image_uri, display_name) 列表。按 URI 去重 (已注册 / 本批重复的跳过),
    空 URI 跳过。返回实际新注册条数。uses 默认 ["dev"]。
    """
    uses = uses or ["dev"]
    seen = {r.get("image_uri") for r in await repo.list_all(workspace_id)}
    n = 0
    for uri, name in images:
        uri = (uri or "").strip()
        if not uri or uri in seen:
            continue
        image_id = _uuid.uuid4().hex[:12]
        await repo.put(
            workspace_id=workspace_id,
            sort_key=tables.ws_image_key(image_id),
            item_fields={
                "image_uri": uri,
                "display_name": (name or "").strip() or _short_name_from_uri(uri),
                "uses": list(uses),
                "source": "ecr-private",
                "creator_username": creator_username,
            },
        )
        seen.add(uri)
        n += 1
    return n
