"""llm-d (多机推理, LWS + sgl-model-gateway) REST routes · 最小切片 (分支B).

独立路由, 与 dynamo/inference 各查各的 resource_type (不混排)。6 端点:
    list / create / preview / get / stop / delete。
不含 (第二批): status-detail / 监控 / 日志 / 终端。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.logging import get_logger
from app.core.security import assert_ws_member, get_current_user
from app.modules.llmd.api.deps import get_k8s_client
from app.modules.llmd.api.schemas import LlmdCreate, LlmdDetail, LlmdListItem
from app.modules.llmd.orchestration import (
    create_llmd_flow,
    delete_flow,
    preview_llmd_flow,
    stop_flow,
    sync_from_k8s,
)
from app.modules.llmd.persistence import crud
from app.modules.llmd.response import build_detail, build_list_item
from app.modules.quota.api.deps import get_hyperpod_client
from app.services.hyperpod_client import HyperPodClient
from app.services.k8s_client import K8sClient

logger = get_logger(__name__)

llmd_router = APIRouter(tags=["llmd"])


@llmd_router.get(
    "/workspaces/{ws_id}/llmd",
    response_model=list[LlmdListItem],
    summary="List llm-d inferences in workspace",
    description=(
        "按创建者过滤:\n"
        "- `scope=mine` (默认): 只返回当前用户创建的 llm-d 推理\n"
        "- `scope=all`: 返回全 ws 所有 · **需超管**\n\n"
        "`phase` 可选, 精确匹配任务态. 取值 = LWS `status.conditions` 里 status=True 的 type "
        "(`Available` / `Progressing` / `UpdateInProgress`; 刚创建一条都没 True 时为空串), "
        "外加平台自己写的 `initializing` (刚创建, controller 还没回写) 与 `Stopped` "
        "(调用 stop 或 LWS 已删).\n\n"
        "**纯读 DDB** — Go platform-controller 维护 phase/kueue_status/endpoint_url. "
        "与 inference 各查各的 `resource_type` (不混排)."
    ),
    responses={403: {"description": "非 ws 成员; 或 scope=all 但非超管"}},
)
async def list_llmd(
    ws_id: str,
    phase: str | None = Query(default=None),
    scope: Literal["mine", "all"] = Query(default="mine"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[LlmdListItem]:
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


@llmd_router.post(
    "/workspaces/{ws_id}/llmd",
    response_model=LlmdDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create llm-d inference",
    description=(
        "在 ws 内下发一组 llm-d 资源 (分支B):\n"
        "1. 校验 `gpu_instance_type` (worker GPU 池) + `gateway_instance_type` (gateway CPU 池) "
        "都在该 ws ComputeQuota 分配机型内\n"
        "2. 模型源: `fsx` 反查该用户被授权的 `model_pvc` 拿真 mount_path; "
        "`s3` 校验 `s3_bucket` ∈ ws 已挂 S3 后**自建专属 PV/PVC** (mount_id = 任务名), 挂 `/model`\n"
        "3. 落 DDB (phase=`initializing`)\n"
        "4. 渲染一组资源 (OTel ConfigMap + gateway RBAC/Deployment/Service + LeaderWorkerSet "
        "`<name>-multi`; `expose_alb=true` 再多渲一个 internal ALB Ingress `alb-<name>`, "
        "HTTP:80 明文) 并提交 K8s; 下发失败回滚 DDB 行 + 已建资源 + 自建 S3 PV/PVC\n\n"
        "任务名 = `display_name` + `-` + 10 位随机后缀 (上限比训练/推理短: `LLMD_NAME_MAX`=31, "
        "故 display_name ≤20 字符), 不查重.\n\n"
        "创建成功即返 phase=`initializing`; 后续状态靠 Go platform-controller 推进."
    ),
    responses={
        403: {
            "description": (
                "非 ws 成员或超管; 或 gpu/gateway instance_type 不在配额机型内; "
                "或 model_pvc 未被授权 / s3_bucket 不在 ws 已挂列表"
            )
        },
        404: {"description": "Workspace 不存在; 或该 ws 无 ComputeQuota"},
        422: {
            "description": (
                "请求体字段校验失败 (display_name 格式 / 传了 name / "
                "fsx 缺 model_pvc / s3 缺 s3_bucket+s3_prefix / nodes_per_replica<2)"
            )
        },
        500: {"description": "K8s 下发 llm-d 资源组失败 (已回滚 DDB 行 + 资源 + S3 PV/PVC)"},
        502: {"description": "S3 模型源自建 PV/PVC 失败 (已回滚 DDB 行 + 半建的 PV/PVC)"},
    },
)
async def create_llmd(
    ws_id: str,
    payload: LlmdCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> LlmdDetail:
    await assert_ws_member(ws_id, current_user)
    row = await create_llmd_flow(None, k8s, hp, ws_id, payload, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@llmd_router.post(
    "/workspaces/{ws_id}/llmd/preview",
    summary="Preview llm-d resources YAML",
    description=(
        "与创建接口共用渲染逻辑 (`_render_resources_from_payload`) → **预览即真相**. "
        "只渲染不落库不下发, 返回 `{\"yaml\": \"...\"}` (`---` 分隔的多文档 YAML: "
        "OTel ConfigMap + gateway RBAC/Deployment/Service + LeaderWorkerSet).\n\n"
        "与 create 的差异: 名字是占位 `<display_name>-xxxxxxxxxx`, `llmd-id` 为 `<preview>`; "
        "S3 源不真建 PV/PVC, PVC 名显示成占位 `<s3-pvc-on-create>`; FSx 授权反查失败时 "
        "model_pvc 用原值占位继续渲染, 不 403 (真 create 会拦).\n\n"
        "机型配额校验仍然生效 (gpu + gateway 都查)."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或 gpu/gateway instance_type 不在配额机型内"
        },
        404: {"description": "Workspace 不存在; 或该 ws 无 ComputeQuota"},
        422: {"description": "请求体字段校验失败 (同创建接口)"},
    },
)
async def preview_llmd(
    ws_id: str,
    payload: LlmdCreate,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    await assert_ws_member(ws_id, current_user)
    yaml_text = await preview_llmd_flow(hp, ws_id, payload, current_user)
    return {"yaml": yaml_text}


@llmd_router.get(
    "/llmd/{id}",
    response_model=LlmdDetail,
    summary="Get llm-d inference detail",
    description=(
        "默认 (`sync=false`) **纯读 DDB** (Go platform-controller 维护 phase/endpoint_url).\n\n"
        "`sync=true` 实时拉 K8s: `LeaderWorkerSet`(`<name>-multi`)`.status.conditions` + "
        "Pods (按 `app.kubernetes.io/instance=<name>` 一把捞 gateway/leader/worker) + "
        "按 ownerRef 关联的 Kueue Workloads; 并现算 `alb_dns` 与 `endpoint_url` "
        "(ALB 有 hostname **且** gateway 有 Ready 副本才给 endpoint_url — ALB 地址比 pod 就绪早得多, "
        "早给会 503).\n\n"
        "sync 结果只对本次响应生效, **不回写** phase/kueue_status/endpoint_url. "
        "唯一落库副作用: LWS 已 404 且 `kueue_status` 非终态 (被 kubectl 绕过平台删掉) 时把该行标 `Stopped`."
    ),
    responses={
        403: {"description": "非该任务所属 ws 的成员且非超管"},
        404: {"description": "llm-d 推理 id 不存在"},
    },
)
async def get_llmd(
    id: str,
    sync: bool = Query(default=False),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> LlmdDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"llmd not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    conditions: list[dict[str, Any]] = []
    pods: list[dict[str, Any]] = []
    workloads: list[dict[str, Any]] = []
    if sync:
        row, conditions, pods, workloads = await sync_from_k8s(None, k8s, row)
    return await build_detail(
        None, row, conditions=conditions, pods=pods, workloads=workloads
    )


@llmd_router.get(
    "/llmd/{id}/kueue-detail",
    summary="llm-d 某 Workload 的 Kueue 实时详情",
    description=(
        "实时查指定 Kueue Workload (`conditions` + `admission`), **不落库**.\n\n"
        "llm-d 一任务多 Workload (每副本组一个 + gateway), 故按 `workload` 名精确查 "
        "(名字从详情接口 `sync=true` 的 `pods[].workload_name` 拿). "
        "找不到该 Workload / 查 K8s 出错 都返 `conditions=[]` + `admission={}` (不报错)."
    ),
    responses={
        403: {"description": "非该任务所属 ws 的成员且非超管"},
        404: {"description": "llm-d 推理 id 不存在 (Workload 查不到不算)"},
    },
)
async def get_llmd_kueue_detail(
    id: str,
    workload: str = Query(..., description="Kueue Workload 名 (来自 pod summary 的 workload_name)"),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"llmd not found: {id}")
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
            logger.info("llmd.kueue_detail.skip", id=str(id), err=str(exc))
    return {"conditions": conditions, "admission": admission}


@llmd_router.post(
    "/llmd/{id}/stop",
    response_model=LlmdDetail,
    summary="Stop llm-d inference (keep DDB row)",
    description=(
        "先把 DDB 行标 phase=`Stopped` + `kueue_status=Finished`, 再删整组 K8s 资源 "
        "(`alb-<name>` Ingress / `<name>-multi` LWS / `<name>-gateway` Deployment+Service+RBAC / "
        "`<name>-otel` ConfigMap; LWS operator 级联回收 pod 组) "
        "释放算力停计费. S3 模型源的自建 PV/PVC 也一并清 (克隆重建会按新名字重新建); "
        "FSx PVC 不动 (那是 ws 共享的).\n\n"
        "DDB 行与全部 spec 保留 (不软删), 支持**先停再看日志 / 克隆重建**.\n\n"
        "单个资源 404 在 adapter 内幂等, 尽力删完.\n\n"
        "返回体同详情接口 (`conditions`/`pods` 为空, 不实时拉 K8s)."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "llm-d 推理 id 不存在"},
        500: {"description": "K8s 删除 llm-d 资源组失败"},
    },
)
async def stop_llmd(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> LlmdDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"llmd not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    row = await stop_flow(None, k8s, id, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@llmd_router.delete(
    "/llmd/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete llm-d inference (cascade)",
    description=(
        "按 name 前缀级联删整组 llm-d 资源 (顺序: `alb-<name>` Ingress → `<name>-multi` "
        "LeaderWorkerSet → `<name>-gateway` Deployment/Service → gateway SA/Role/RoleBinding → "
        "`<name>-otel` ConfigMap; pod 组由 LWS operator 级联回收, ALB/TG/SG 靠 "
        "aws-load-balancer-controller 的 finalizer 回收). "
        "先摘 Ingress 再删后端, 免得中途 502.\n\n"
        "S3 模型源的自建 PV/PVC 一并清掉; FSx PVC 不动 (那是 ws 共享的).\n\n"
        "K8s 资源删完再**软删** DDB 行: 打 `deleted_at` 标记, 不硬删 — 列表页过滤掉, 审计仍可查.\n\n"
        "**幂等**: 单个资源 404 在 adapter 内跳过, 尽力删完; 重复删同一行仍返 204.\n\n"
        "**权限**: 端点层要求 ws 成员或超管; 内部再校验 creator 本人 / ws 管理员 / 平台超管."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "llm-d 推理 id 不存在"},
        500: {"description": "K8s 删除 llm-d 资源组失败 (非 404)"},
    },
)
async def delete_llmd(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"llmd not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    await delete_flow(None, k8s, id, current_user)
    return None
