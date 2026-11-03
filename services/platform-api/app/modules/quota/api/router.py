"""Quota HTTP 路由 (DDB-only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.aws._ttl_cache import TtlCache
from app.core.logging import get_logger
from app.core.security import assert_ws_member, get_current_user, require_admin
from app.modules.quota.api.deps import get_hyperpod_client
from app.modules.quota.api.schemas import (
    ComputeQuota,
    CreateComputeQuotaPayload,
    QuotaUsage,
    UpdateComputeQuotaPayload,
)
from app.modules.quota.orchestration import (
    create_workspace_quota,
    delete_workspace_quota,
    fetch_quota_usage,
    get_workspace_quota,
    update_workspace_quota,
)
from app.modules.workspace import crud as workspace_crud
from app.services.hyperpod_client import HyperPodClient

logger = get_logger(__name__)

quota_router = APIRouter(tags=["quota"])

_USAGE_CACHE_TTL_SEC = 5
_usage_cache: TtlCache[dict[str, Any]] = TtlCache(ttl_seconds=_USAGE_CACHE_TTL_SEC)


# ============================================================
# Workspace 视角 · ComputeQuota 生命周期
# ============================================================

@quota_router.get(
    "/workspaces/{ws_id}/quota",
    response_model=ComputeQuota,
    response_model_by_alias=True,
    summary="查询 ws 绑定的 ComputeQuota",
    description=(
        "查询该 workspace 绑定的 SageMaker HyperPod **ComputeQuota** (静态配额定义), "
        "含实例类型 / 台数 / 借用策略 / 抢占策略 / TeamName 等.\n\n"
        "**规格回填 (2026-07-24)**: 每条 `resources[]` 由 `_tag_resource_pools` 附加 "
        "`pool` (gpu/cpu) · `gpu_spec` (如 `4×A10G`) · `gpu_type` (如 `L4/H100`) · "
        "`vCpu` · `memoryInGiB` · `accelerators`, 走 us-east-1 EC2 `DescribeInstanceTypes` "
        "为唯一权威源 (前端不再维护静态表). Trainium (NeuronInfo) **暂不计入 accelerators**.\n\n"
        "**权限**: 仅 ws 成员或超管 (越权修复 2026-06-14).\n\n"
        "**数据源**: SageMaker `DescribeComputeQuota` (实时) + EC2 `DescribeInstanceTypes` "
        "(TTL 缓存). ws 表里存的是 `sagemaker_compute_quota_id`, 每次调用即透传给 SageMaker.\n\n"
        "**注意**: 这是**静态配额**, 想看实时用量请调 `/quota/usage`."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace 不存在或未绑定 ComputeQuota"},
        500: {"description": "SageMaker DescribeComputeQuota 失败 (未映射专用状态码)"},
    },
)
async def get_workspace_quota_endpoint(
    ws_id: str,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ComputeQuota:
    # 仅 ws 成员或超管可看配额 (越权修复 2026-06-14):
    # 原端点连 current_user 都没有, 知道 ws_id 即可看别人团队的配额。
    await assert_ws_member(ws_id, current_user)
    return await get_workspace_quota(None, hp, ws_id)


@quota_router.post(
    "/workspaces/{ws_id}/quota",
    response_model=ComputeQuota,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
    summary="为 ws 创建 ComputeQuota",
    description=(
        "为该 ws 创建一份 SageMaker ComputeQuota, 并把返回的 `ComputeQuotaId` 落到 ws 表 "
        "(`compute_quota_id`), 作为该 ws 后续所有算力隔离的依据. "
        "`ComputeQuotaArn` 只写日志, **不落库**.\n\n"
        "SageMaker HyperPod 内部会连锁产出:\n"
        "1. K8s namespace (ws 专属)\n"
        "2. Kueue `ClusterQueue` + `LocalQueue` (排队/借用/抢占)\n"
        "3. `ResourceQuota` (硬上限)\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `CreateComputeQuota` API. 返回体 `resources[]` 与 GET 一致, "
        "回填 `pool / gpu_spec / gpu_type / vCpu / memoryInGiB` (写读契约一致)."
    ),
    responses={
        400: {"description": "Cluster 未配置 hyperpod_cluster_arn"},
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "Workspace 不存在"},
        422: {"description": "payload 校验失败"},
        500: {"description": "SageMaker CreateComputeQuota / DescribeComputeQuota 失败 (未映射专用状态码)"},
    },
)
async def create_workspace_quota_endpoint(
    ws_id: str,
    payload: CreateComputeQuotaPayload,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(require_admin),
) -> ComputeQuota:
    del current_user
    return await create_workspace_quota(None, hp, ws_id, payload)


@quota_router.patch(
    "/workspaces/{ws_id}/quota",
    response_model=ComputeQuota,
    response_model_by_alias=True,
    summary="更新 ws 的 ComputeQuota",
    description=(
        "更新该 ws 已绑定的 ComputeQuota (调整实例台数 / 借用策略 / 抢占策略 / FairShareWeight 等).\n\n"
        "**AWS 侧是完整替换语义**: 服务端先 `DescribeComputeQuota` 拿当前值, "
        "把 payload 里非空字段 merge 上去再整体 update. "
        "`TargetVersion` 也由服务端从 describe 结果里取, **payload 不需要 (也没有) 版本字段**.\n\n"
        "**无变更短路**: merge 后与当前值完全相同时直接返回当前 quota, 不调 AWS.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `UpdateComputeQuota` API. 返回体 `resources[]` 同 GET, "
        "回填 `pool / gpu_spec / gpu_type / vCpu / memoryInGiB`."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "Workspace 不存在或未绑定 ComputeQuota"},
        422: {"description": "payload 校验失败"},
        500: {"description": "SageMaker Describe / UpdateComputeQuota 失败 (含版本冲突, 未映射专用状态码)"},
    },
)
async def update_workspace_quota_endpoint(
    ws_id: str,
    payload: UpdateComputeQuotaPayload,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(require_admin),
) -> ComputeQuota:
    del current_user
    return await update_workspace_quota(None, hp, ws_id, payload)


@quota_router.delete(
    "/workspaces/{ws_id}/quota",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除 ws 的 ComputeQuota",
    description=(
        "删除该 ws 绑定的 ComputeQuota, 并清空 ws 表里的 `sagemaker_compute_quota_id`. "
        "对应 Kueue ClusterQueue / ResourceQuota 会被 SageMaker HyperPod 一并回收.\n\n"
        "**非幂等**: ws 未绑定配额时返 404; AWS 侧配额已被删掉时 SageMaker 报错 → 500.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DeleteComputeQuota` API."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "Workspace 不存在或未绑定 ComputeQuota"},
        500: {"description": "SageMaker DeleteComputeQuota 失败 (未映射专用状态码)"},
    },
)
async def delete_workspace_quota_endpoint(
    ws_id: str,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(require_admin),
) -> None:
    del current_user
    await delete_workspace_quota(None, hp, ws_id)
    return None


# ============================================================
# Workspace 视角 · Kueue 实时用量
# ============================================================

@quota_router.get(
    "/workspaces/{ws_id}/quota/usage",
    response_model=QuotaUsage,
    response_model_by_alias=True,
    tags=["quota-usage"],
    summary="查询 ws 实时算力用量",
    description=(
        "查询该 ws 的**实时**算力用量, ws 概览页配额进度条使用.\n\n"
        "**响应字段**: `resources[]` 每项按 flavor 给 `instanceType` (= Kueue flavor 名) · "
        "`acceleratorsUsed` · `acceleratorsPending` · `vCpuUsed` · `memoryUsedInGiB`; "
        "另有跨 flavor 的 `totals` 与 `capturedAt`. "
        "**不返回额度上限 / 借用量** (Kueue status 里没有 nominalQuota / borrowed 数据) — "
        "额度定义请调 `/quota`.\n\n"
        "`acceleratorsPending` 来自 `ClusterQueue.status.pendingWorkloads`, "
        "按 flavor 不可拆, 只挂在 `totals` 上.\n\n"
        "**权限**: 仅 ws 成员或超管 (越权修复 2026-06-14).\n\n"
        "**数据源**: K8s Kueue `ClusterQueue.status.flavorsUsage` (缺失时退 `flavorsReservation`), "
        "ClusterQueue 名按 `hyperpod-ns-{ws.name}-clusterqueue` 推. "
        "查不到该 CR 时返 `resources: []` + `totals` 全 0 (不报错). "
        "本端点带 5s 内存 TTL 缓存, 避免高频页面刷新压 kube-apiserver.\n\n"
        "**与 `/quota` 区别**: `/quota` 是 SageMaker 的静态配额定义, "
        "本端点是 Kueue 视角的动态使用情况."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace 不存在"},
        500: {"description": "Kueue ClusterQueue 查询失败 (未映射专用状态码)"},
    },
)
async def get_quota_usage_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> QuotaUsage:
    # 仅 ws 成员或超管可看实时用量 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    ws = await workspace_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workspace not found: {ws_id}",
        )

    ws_name = ws.get("name") or ws.get("display_name") or ""

    async def _load() -> dict[str, Any]:
        usage = await fetch_quota_usage(ws_name)
        return usage.model_dump(by_alias=True, mode="json")

    cached = await _usage_cache.get_or_load(f"{ws_id}", _load)
    logger.info(
        "quota_usage.ok",
        ws_id=str(ws_id),
        team=ws_name,
        flavors=len(cached.get("resources", [])),
    )
    return QuotaUsage.model_validate(cached)

# NOTE: GET /clusters/{cluster_tag}/quotas 由 cluster 模块的 cluster_router 提供
# (api/v1/router.py 里 cluster_router 先注册 → 实际生效)。此处原有同路径端点是
# 死代码 (永不命中) 且触发 FastAPI Duplicate Operation ID 警告, 已删 (2026-06-14)。
