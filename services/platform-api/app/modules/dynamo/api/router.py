"""Dynamo (多机推理) REST routes · 最小切片.

独立路由, 与 inference 各查各的 resource_type (不混排)。最小切片端点:
    list / create / preview / get / stop / delete。
不含 (第二批): sync / status-detail / kueue-detail / 监控 / 日志 / 终端。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.logging import get_logger
from app.core.security import assert_ws_member, get_current_user
from app.modules.dynamo.api.deps import get_k8s_client
from app.modules.dynamo.api.schemas import (
    DynamoCreate,
    DynamoDetail,
    DynamoListItem,
)
from app.modules.dynamo.orchestration import (
    create_dynamo_flow,
    delete_flow,
    preview_dynamo_flow,
    stop_flow,
    sync_from_k8s,
)
from app.modules.dynamo.persistence import crud
from app.modules.dynamo.response import build_detail, build_list_item
from app.modules.quota.api.deps import get_hyperpod_client
from app.services.hyperpod_client import HyperPodClient
from app.services.k8s_client import K8sClient

logger = get_logger(__name__)

dynamo_router = APIRouter(tags=["dynamo"], include_in_schema=False)


@dynamo_router.get(
    "/workspaces/{ws_id}/dynamo-inferences",
    response_model=list[DynamoListItem],
    summary="List dynamo inferences in workspace",
    description=(
        "按创建者过滤:\n"
        "- `scope=mine` (默认): 只返回当前用户创建的多机推理\n"
        "- `scope=all`: 返回全 ws 所有多机推理 · **需超管**\n\n"
        "`phase` 可选, 精确匹配任务态 (`DeploymentInProgress` / `DeploymentComplete` / …).\n\n"
        "**纯读 DDB** — informer 实时维护 phase/endpoint_url, 不额外请求 K8s. "
        "与单机 inference 各查各的 `resource_type` (不混排)."
    ),
    responses={
        403: {"description": "非 ws 成员; 或 scope=all 但非超管"},
    },
)
async def list_dynamo(
    ws_id: str,
    phase: str | None = Query(default=None),
    scope: Literal["mine", "all"] = Query(default="mine"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[DynamoListItem]:
    await assert_ws_member(ws_id, current_user)
    if scope == "all":
        if not current_user.get("is_admin"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "scope=all requires admin; use scope=mine"
            )
        creator_filter: Any = None
    else:
        creator_filter = current_user.get("user_id") or current_user.get("id")
    rows = await crud.list_by_workspace(
        None, ws_id, phase=phase, creator_user_id=creator_filter
    )
    items = await asyncio.gather(*(build_list_item(None, r) for r in rows))
    return list(items)


@dynamo_router.post(
    "/workspaces/{ws_id}/dynamo-inferences",
    response_model=DynamoDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create dynamo inference",
    description=(
        "在 ws 内下发一个 Dynamo 多机推理:\n"
        "1. 渲染 `DynamoGraphDeployment` CR (Grove operator, OpenAI 兼容 ClusterIP :8000)\n"
        "2. 落 DDB (phase=`DeploymentPending`)\n"
        "3. 提交 K8s (Grove operator 接手部署多机 pod 组)\n\n"
        "创建成功即返 phase=`DeploymentPending`; 后续状态靠 controller informer 推进."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace / 资源模板不存在"},
        409: {"description": "同 ws 内已有同名多机推理"},
        422: {"description": "启动脚本 / 端口 / 模型路径 / 副本参数 校验失败"},
    },
)
async def create_dynamo(
    ws_id: str,
    payload: DynamoCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DynamoDetail:
    await assert_ws_member(ws_id, current_user)
    row = await create_dynamo_flow(None, k8s, hp, ws_id, payload, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@dynamo_router.post(
    "/workspaces/{ws_id}/dynamo-inferences/preview",
    summary="Preview dynamo CR YAML",
    description=(
        "与创建接口共用渲染逻辑 → **预览即真相**, 所见即所得. "
        "前端创建表单最后一步用来给用户 diff 确认."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace / 资源模板不存在"},
    },
)
async def preview_dynamo(
    ws_id: str,
    payload: DynamoCreate,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    await assert_ws_member(ws_id, current_user)
    yaml_text = await preview_dynamo_flow(hp, ws_id, payload, current_user)
    return {"yaml": yaml_text}


@dynamo_router.get(
    "/dynamo-inferences/{id}",
    response_model=DynamoDetail,
    summary="Get dynamo inference detail",
    description=(
        "默认 **纯读 DDB** (informer 实时维护 phase/endpoint_url).\n\n"
        "`sync=true` 实时拉 K8s `DynamoGraphDeployment.status.conditions` + Pods "
        "(详情页状态时间线 / Pod 表用). sync 只对本次响应生效, 不落库."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "多机推理不存在"},
    },
)
async def get_dynamo(
    id: str,
    sync: bool = Query(default=False),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DynamoDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dynamo not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    conditions: list[dict[str, Any]] = []
    pods: list[dict[str, Any]] = []
    if sync:
        row, conditions, pods = await sync_from_k8s(None, k8s, row)
    return await build_detail(None, row, conditions=conditions, pods=pods)


@dynamo_router.get(
    "/dynamo-inferences/{id}/status-detail",
    summary="Get dynamo raw status detail",
    description=(
        "按需单查 `status_detail` 全量 JSON (含 K8s 原始 conditions/events), "
        "详情页 debug 弹窗用. 不会触发 sync."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "多机推理不存在"},
    },
)
async def get_dynamo_status_detail(
    id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dynamo not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return {"status_detail": row.get("status_detail")}


@dynamo_router.post(
    "/dynamo-inferences/{id}/stop",
    response_model=DynamoDetail,
    summary="Stop dynamo inference (keep DDB row)",
    description=(
        "删 K8s `DynamoGraphDeployment` CR, Grove operator 级联回收 pod 组以释放算力 + 停计费, "
        "DDB 行保留 (phase=`Stopped`).\n"
        "用于**先停再看日志 / 克隆参数**的场景. 后续可再 clone 出新多机推理."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "多机推理不存在"},
    },
)
async def stop_dynamo(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DynamoDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dynamo not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    row = await stop_flow(None, k8s, id, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@dynamo_router.delete(
    "/dynamo-inferences/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete dynamo inference (cascade)",
    description=(
        "级联删 `DynamoGraphDeployment` CR + Grove operator 管理的 pod 组. "
        "DDB 行 phase 走 `DeletionInProgress → DeletionComplete` 后 GC. "
        "**幂等**: 删已删返 204."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "多机推理不存在"},
    },
)
async def delete_dynamo(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dynamo not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    await delete_flow(None, k8s, id, current_user)
    return None
