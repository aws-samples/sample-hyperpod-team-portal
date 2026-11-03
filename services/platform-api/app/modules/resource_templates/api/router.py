"""资源模板 REST routes (开发机/训练/推理 统一一套, 仅 admin 管).

端点自带 /workspaces/{ws_id}/resource-templates 前缀。
2026-06-14 确定: 三类共用一套模板; 用户只能列 (选), 增删改仅 ws admin。
- GET    list   (全员可见)
- POST   create (仅 ws admin)
- PUT    update (仅 ws admin)
- DELETE delete (仅 ws admin)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.core.security import get_current_user
from app.modules.resource_templates.api.schemas import (
    TemplateCreate,
    TemplateItem,
    TemplateUpdate,
)
from app.modules.resource_templates.orchestration import service

resource_templates_router = APIRouter(tags=["resource-templates"])


@resource_templates_router.get(
    "/workspaces/{ws_id}/resource-templates",
    response_model=list[TemplateItem],
    summary="列本 ws 的资源模板",
    description=(
        "返本 ws 全部资源模板 (`gpu` / `cpu_cores` / `mem_gib` 单值打包, K8s req=lim). "
        "开发机 / 训练 / 推理**共用一套**, 创建表单在此下拉选一档.\n\n"
        "- **副作用**: 本 ws 一档模板都没有时, 首次读会**懒 seed 4 档内置预置** "
        "(小 / 中 / 大 / 超大规格, `creator_username=system`) 再返回\n\n"
        "**权限**: ws 成员或平台超管 (下拉选用是全员刚需). ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管 (含 ws 不存在)"},
    },
)
async def list_resource_templates(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[TemplateItem]:
    rows = await service.list_templates(ws_id, current_user)
    return [TemplateItem(**r) for r in rows]


@resource_templates_router.post(
    "/workspaces/{ws_id}/resource-templates",
    response_model=TemplateItem,
    status_code=status.HTTP_201_CREATED,
    summary="新建资源模板",
    description=(
        "在本 ws 建一档资源模板 (`gpu` / `cpu_cores` / `mem_gib` 组合). "
        "建成后即刻出现在开发机 / 训练 / 推理创建下拉里.\n\n"
        "- **不做同名去重**: 同名模板可重复创建, 每次生成新 `template_id`\n"
        "- 字段边界: gpu 0-8 / cpu_cores 0-128 / mem_gib 0-1024, 越界 422\n\n"
        "**权限**: 仅本 ws 管理员或平台超管 (普通成员不能加档). "
        "非 ws 成员 / ws 不存在同样 403."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员; 或非 ws 管理员且非超管"},
        422: {"description": "name / gpu / cpu_cores / mem_gib 校验失败"},
    },
)
async def create_resource_template(
    ws_id: str,
    payload: TemplateCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TemplateItem:
    row = await service.create_template(ws_id, payload, current_user)
    return TemplateItem(**row)


@resource_templates_router.put(
    "/workspaces/{ws_id}/resource-templates/{template_id}",
    response_model=TemplateItem,
    summary="更新资源模板",
    description=(
        "改本 ws 一档资源模板 (`name` / `description` / `resource` 传了才改, 其余字段保留).\n\n"
        "- **不影响已建任务**: 平台不记录任务与模板的关联 (无 `template_id` 落库), 模板只是"
        "创建表单的下拉预设, 选中后数值即展开写进任务本身; 改模板只影响之后的创建\n\n"
        "**权限**: 仅本 ws 管理员或平台超管. 非 ws 成员 / ws 不存在同样 403."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员; 或非 ws 管理员且非超管"},
        404: {"description": "模板不存在 (本 ws 下无此 template_id)"},
        422: {"description": "字段校验失败"},
    },
)
async def update_resource_template(
    ws_id: str,
    template_id: str,
    payload: TemplateUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TemplateItem:
    row = await service.update_template(ws_id, template_id, payload, current_user)
    return TemplateItem(**row)


@resource_templates_router.delete(
    "/workspaces/{ws_id}/resource-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除资源模板",
    description=(
        "从本 ws 删一档模板. 已建任务不受影响 (任务不引用模板, 创建时数值已展开写入任务本身).\n\n"
        "- 注意: 若删空了本 ws 所有模板, 下次 GET 会重新懒 seed 4 档内置预置\n\n"
        "**权限**: 仅本 ws 管理员或平台超管. **幂等**: 删不存在 / 已删的也返 204."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员; 或非 ws 管理员且非超管"},
    },
)
async def delete_resource_template(
    ws_id: str,
    template_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    await service.delete_template(ws_id, template_id, current_user)
