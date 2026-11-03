"""Inference REST routes (DDB-only)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.core.logging import get_logger
from app.core.security import assert_ws_member, get_current_user
from app.modules.inference.api.deps import get_k8s_client
from app.modules.quota.api.deps import get_hyperpod_client
from app.services.hyperpod_client import HyperPodClient
from app.modules.inference.api.schemas import (
    InferenceCreate,
    InferenceDetail,
    InferenceListItem,
)
from app.modules.inference.orchestration import (
    create_inference_flow,
    delete_flow,
    preview_inference_flow,
    stop_flow,
    sync_from_k8s,
)
from app.modules.inference.persistence import crud
from app.modules.shared.kueue_status import pick_latest_pod
from app.modules.inference.response import build_detail, build_list_item
from app.services.k8s_client import K8sClient

logger = get_logger(__name__)

inference_router = APIRouter(tags=["inferences"])


@inference_router.get(
    "/workspaces/{ws_id}/inferences",
    response_model=list[InferenceListItem],
    summary="列出工作空间下的推理服务",
    description=(
        "按创建者过滤:\n"
        "- `scope=mine` (默认): 只返回当前用户创建的推理\n"
        "- `scope=all`: 返回全 ws 所有推理 · **需超管**\n\n"
        "`phase` 可选, 精确匹配任务态. 取值 = CR `status.deploymentStatus."
        "deploymentObjectOverallState` 原始值 (`DeploymentInProgress` / `DeploymentComplete` / "
        "`DeploymentFailed` / `Deletion*`, 缺失回退 `status.state`), 外加平台自己写的 "
        "`Pending` (刚创建, informer 还没回写) 与 `Stopped` (调用 stop).\n\n"
        "**纯读 DDB** — informer 实时维护 phase/endpoint_url, 不额外请求 K8s."
    ),
    responses={
        403: {"description": "非 ws 成员; 或 scope=all 但非超管"},
    },
)
async def list_inferences(
    ws_id: str,
    phase: str | None = Query(default=None),
    scope: Literal["mine", "all"] = Query(default="mine"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[InferenceListItem]:
    # 纯读 DDB (A3): informer 实时维护 phase/endpoint_url, 不再请求时 sync K8s。
    # 非 ws 成员一律 403 (越权修复 2026-06-14)。
    await assert_ws_member(ws_id, current_user)
    if scope == "all":
        if not current_user.get("is_admin"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "scope=all requires admin; use scope=mine",
            )
        creator_filter: Any = None
    else:
        creator_filter = current_user.get("user_id") or current_user.get("id")

    rows = await crud.list_by_workspace(
        None, ws_id, phase=phase, creator_user_id=creator_filter
    )
    items = await asyncio.gather(*(build_list_item(None, r) for r in rows))
    return list(items)


@inference_router.post(
    "/workspaces/{ws_id}/inferences",
    response_model=InferenceDetail,
    status_code=status.HTTP_201_CREATED,
    summary="创建推理服务",
    description=(
        "在 ws 内下发一个 SGLang 推理服务 (`framework` 目前只支持 `sglang`):\n"
        "1. 先落 DDB (phase=`Pending`)\n"
        "2. 渲染 `InferenceEndpointConfig` CR (模型源 fsx/s3/huggingface, 资源, replicas, "
        "路由策略, L2 KV cache, `public_endpoint` 决定是否建公网 SageMaker endpoint)\n"
        "3. 提交 K8s (SageMaker HyperPod inference operator 接手部署); 下发失败回滚 DDB 行\n"
        "4. 归档真实下发的 CR YAML 到 ws 第一个 S3 挂载 (失败不阻断)\n\n"
        "任务名不查重: `name` = `display_name` + `-` + 10 位随机后缀, 由后端派生 "
        "(请勿自己传 `name`).\n\n"
        "创建成功即返 phase=`Pending`; 后续状态靠 platform-worker informer 推进."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或 instance_type 不在该 ws ComputeQuota 分配机型内"
        },
        404: {"description": "Workspace 不存在; 或该 ws 无 ComputeQuota"},
        422: {
            "description": (
                "请求体字段校验失败 (display_name 格式 / 传了 name / "
                "model_source_type 与 fsx·s3·huggingface 不匹配 / 资源与端口范围)"
            )
        },
        500: {"description": "K8s 下发 InferenceEndpointConfig 失败 (DDB 行已回滚)"},
    },
)
async def create_inference(
    ws_id: str,
    payload: InferenceCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> InferenceDetail:
    # 仅 ws 成员或超管可在此 ws 提交推理服务 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    row = await create_inference_flow(None, k8s, hp, ws_id, payload, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@inference_router.post(
    "/workspaces/{ws_id}/inferences/preview",
    summary="预览渲染后的 IEC CR YAML (不创建)",
    description=(
        "与创建接口共用渲染逻辑 (`_render_cr_from_payload`) → **预览即真相**, 所见即所得. "
        "只渲染不落库不下发, 返回 `{\"yaml\": \"...\"}`.\n\n"
        "预览里的服务名/模型名是占位 `<display_name>-xxxxxxxxxx` (真名只在 create 时派生一次), "
        "`inference-id` 为 `<preview>`.\n\n"
        "前端创建表单最后一步用来给用户 diff 确认."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或 instance_type 不在该 ws ComputeQuota 分配机型内"
        },
        404: {"description": "Workspace 不存在; 或该 ws 无 ComputeQuota"},
        422: {"description": "请求体字段校验失败 (同创建接口)"},
    },
)
async def preview_inference(
    ws_id: str,
    payload: InferenceCreate,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    # 仅 ws 成员或超管可预览 (泄露 ws namespace 等内部配置) (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    yaml_text = await preview_inference_flow(hp, ws_id, payload, current_user)
    return {"yaml": yaml_text}


@inference_router.get(
    "/inferences/{id}",
    response_model=InferenceDetail,
    summary="查询推理服务详情",
    description=(
        "默认 (`sync=false`) **纯读 DDB** (informer 实时维护 phase/endpoint_url), 秒响应.\n\n"
        "`sync=true` 实时拉 K8s: IEC CR status + ALB DNS + Pods + 关联 Kueue Workload, "
        "并返回**固定 4 阶段骨架** `conditions` (`Progressing` / `Available` / "
        "`LoadBalancer` / `SageMakerEndpoint`, 未达成的给 status=`Unknown` 占位) 供详情页状态时间线用.\n\n"
        "⚠️ `sync=true` **会落库**: `endpoint_url` / `alb_dns` 变了才写 DDB (dirty check); "
        "phase/status_detail 归 informer 维护, 本接口不写. 另: CR 已 404 且 kueue_status 非终态 "
        "(被 kubectl 绕过平台删掉) 时会把该行标成 `Stopped`."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理不存在"},
    },
)
async def get_inference(
    id: str,
    sync: bool = Query(default=False),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> InferenceDetail:
    # 默认纯读 DDB (A3): informer 维护 phase/endpoint_url。
    # sync=true 时实时拉 IEC .status.conditions + pods (详情页状态时间线/Pod 表用)。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    # 仅该 inference 所属 ws 的成员或超管可看 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    conditions: list[dict[str, Any]] = []
    pods: list[dict[str, Any]] = []
    workloads: list[dict[str, Any]] = []
    if sync:
        row, conditions, pods, workloads = await sync_from_k8s(None, k8s, row)
    return await build_detail(
        None, row, conditions=conditions, pods=pods, workloads=workloads
    )


@inference_router.get(
    "/inferences/{id}/status-detail",
    summary="推理服务原始 status detail",
    description=(
        "按需单查 `status_detail` 全量 JSON = informer 落库的三段快照 "
        "(`state` + IEC CR 原始 `conditions` + `deploymentStatus`), 详情页 debug 弹窗用.\n\n"
        "内容大, 不在 list 接口返回; 本接口只读 DDB, 不请求 K8s / 不触发 sync. "
        "informer 还没回写时返 `{\"status_detail\": null}`."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理不存在"},
    },
)
async def get_inference_status_detail(
    id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return {"status_detail": row.get("status_detail")}


@inference_router.get(
    "/inferences/{id}/kueue-detail",
    summary="推理 Kueue Workload 实时详情",
    description=(
        "实时查该推理背后的 Kueue Workload (`conditions` + `admission`), **不落库**.\n\n"
        "推理走 2 跳: 最新 Pod (`app=<cr名>`) uid → Workload. 找不到 Pod 时返 conditions=[]."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理不存在"},
    },
)
async def get_inference_kueue_detail(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # 推理 2 跳: 最新 Pod (app=<cr名>) uid → Workload。实时查, 不落库。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    ns = row.get("k8s_namespace") or ""
    name = row.get("k8s_endpoint_name") or ""
    conditions: list[dict[str, Any]] = []
    admission: dict[str, Any] = {}
    if ns and name:
        try:
            pods = await k8s.list_pods_by_label_selector(ns, f"app={name}")
            pod = pick_latest_pod(pods)
            if pod is not None:
                pod_uid = (pod.get("metadata") or {}).get("uid") or ""
                wls = await k8s.list_workloads_by_job_uid(ns, pod_uid)
                wl_status = (pick_latest_pod(wls) or {}).get("status") or {}
                conditions = wl_status.get("conditions") or []
                admission = wl_status.get("admission") or {}
        except Exception as exc:
            logger.info("inference.kueue_detail.skip", id=str(id), err=str(exc))
    return {"conditions": conditions, "admission": admission}


@inference_router.get(
    "/inferences/{id}/kueue-detail-by-workload",
    summary="推理某副本 Workload 的 Kueue 实时详情",
    description=(
        "实时查指定 Kueue Workload (`conditions` + `admission`), **不落库**.\n\n"
        "推理多副本每 Pod 一个 pod 级 Workload, 按 `workload` 名精确查 (副本卡片用). "
        "找不到该 Workload 时返 `conditions=[]`."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理不存在"},
    },
)
async def get_inference_kueue_detail_by_workload(
    id: str,
    workload: str = Query(..., description="Kueue Workload 名 (来自 pod summary 的 workload_name)"),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    ns = row.get("k8s_namespace") or ""
    conditions: list[dict[str, Any]] = []
    admission: dict[str, Any] = {}
    if ns and workload:
        try:
            wls = await k8s.list_workloads(ns)
            wl = next(
                (w for w in wls if (w.get("metadata") or {}).get("name") == workload),
                None,
            )
            if wl is not None:
                st = wl.get("status") or {}
                conditions = st.get("conditions") or []
                admission = st.get("admission") or {}
        except Exception as exc:  # noqa: BLE001
            logger.info("inference.kueue_detail_by_wl.skip", id=str(id), err=str(exc))
    return {"conditions": conditions, "admission": admission}


@inference_router.post(
    "/inferences/{id}/stop",
    response_model=InferenceDetail,
    summary="停止推理服务 (保留 DDB 行)",
    description=(
        "先把 DDB 行标 phase=`Stopped` + 清空 `endpoint_url` + 置 `stop_requested` 哨兵, "
        "再删 `InferenceEndpointConfig` CR (operator 级联 Pod / ALB / SageMaker endpoint) "
        "以释放算力停计费. DDB 行与全部 spec 保留 (不软删), 支持**先停再看日志 / 克隆重建**.\n\n"
        "先标后删的顺序是必须的: 否则并发的详情页 `sync=true` 撞 CR 404 时会误判.\n\n"
        "**幂等**: CR 已不在 (K8s 404) 照样返回已标 Stopped 的行.\n\n"
        "返回体同详情接口 (`conditions`/`pods` 为空, 不实时拉 K8s)."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "推理 id 不存在"},
        500: {"description": "K8s 删除 InferenceEndpointConfig 失败 (非 404)"},
    },
)
async def stop_inference(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> InferenceDetail:
    # 停止: 删 K8s 资源释放算力+停计费, DDB 行保留 (可看日志/克隆)。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    row = await stop_flow(None, k8s, id, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@inference_router.delete(
    "/inferences/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除推理服务",
    description=(
        "删 `InferenceEndpointConfig` CR (operator 级联 Pods + ALB + SageMaker endpoint, "
        "若开了 `public_endpoint`), 然后**软删** DDB 行: 打 `deleted_at` 标记, 不硬删 — "
        "列表页过滤掉, 审计仍可查.\n\n"
        "**幂等**: CR 已不存在 (K8s 404) 视为成功, 重复删同一行仍返 204.\n\n"
        "**权限**: 端点层要求 ws 成员或超管; 内部再校验 creator 本人 / ws 管理员 / 平台超管."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "推理 id 不存在"},
        500: {"description": "K8s 删除 InferenceEndpointConfig 失败"},
    },
)
async def delete_inference(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    # 删前先校验调用者是该 inference 所属 ws 的成员/超管 (越权修复 2026-06-14):
    # 端点层快速失败; delete_flow 内部再兜底鉴权 + 审计留痕。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    await delete_flow(None, k8s, id, current_user)
    return None
