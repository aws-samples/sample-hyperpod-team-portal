"""DevInstance HTTP 路由 (DDB-only)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.logging import get_logger
from app.core.security import assert_ws_member, get_current_user
from app.modules.shared.kueue_status import pick_latest_pod
from app.modules.workspace import crud as ws_crud

from ..orchestration import (
    add_authorized_key_flow,
    create_custom_template,
    create_dev_instance_flow,
    delete_custom_template,
    delete_flow,
    list_permitted_mounts,
    list_shared_pvcs,
    list_templates,
    maybe_recover_ssm,
    patch_template_allowed_images,
    register_ssm_in_sidecar,
    resize_flow,
    start_flow,
    stop_flow,
    sync_from_k8s,
    update_flow,
)
from ..persistence import crud
from ..response import build_access_info, build_detail, build_list_item
from app.modules.quota.api.deps import get_hyperpod_client
from app.services.hyperpod_client import HyperPodClient

from .deps import get_k8s_client
from .schemas import (
    AccessInfo,
    AuthorizedKeyAdd,
    AuthorizedKeyResult,
    DevInstanceCreate,
    DevInstanceDetail,
    DevInstanceListItem,
    DevInstanceResize,
    DevInstanceUpdate,
    SharedPVCInfo,
    TemplateCreate,
    TemplateInfo,
    TemplatePatchAllowedImages,
)

logger = get_logger(__name__)

router = APIRouter(tags=["dev-instances"])


@router.get(
    "/workspaces/{ws_id}/shared-pvcs",
    response_model=list[SharedPVCInfo],
    summary="列出当前用户可挂载的共享 FSx",
    description=(
        "返回当前用户在指定 ws 内被授权挂载的 FSx PVC 列表, 创建开发机时用作挂载卷候选.\n\n"
        "- 数据源 `MountPermissions` (username-index GSI), 按 `username` 精确匹配, "
        "**仅返回当前用户实际被授权的**, 不是 ws 下的全量 PVC.\n"
        "- **只含 FSx 挂载**; ws 的 S3 挂载不在此列表 (S3 无成员级权限).\n"
        "- 每项按 `access` 返回 ro/rw 对应的 PVC 名; 主目录 (gid == ws.primary_gid) "
        "标 `is_primary=true` 并排在第一.\n"
        "- 纯读操作, 不改任何资源. 只校验 ws 存在, **不校验 ws 成员** (返回内容天然按 username 收窄)."
    ),
    responses={
        404: {"description": "Workspace 不存在"},
    },
)
async def list_shared_pvcs_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[SharedPVCInfo]:
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    return await list_permitted_mounts(ws_id, username)


@router.post(
    "/admin/dev-instance-templates",
    response_model=dict,
    summary="[管理员] 创建自定义 WorkspaceTemplate",
    status_code=status.HTTP_201_CREATED,
    description=(
        "**仅平台管理员**可用. 创建 BYOI (Bring-Your-Own-Image) 自定义模板.\n\n"
        "- 模板即 K8s `WorkspaceTemplate` CR (workspace.jupyter.org, ns=`jupyter-k8s-system`), "
        "记录允许的镜像白名单 / 资源规格.\n"
        "- 与系统内置模板并列, 会出现在 `GET /dev-instance-templates` 里, 可编辑/删除 "
        "(见对应 PATCH/DELETE 接口).\n"
        "- ⚠️ **暂不能用于创建开发机**: `DevInstanceCreate.template_name` 目前是白名单 "
        "(仅 `sagemaker-jupyter-template` / `sagemaker-code-editor-template`).\n"
        "- 非幂等, 但同名冲突不单独映射: K8s AlreadyExists 与其他 K8s 错误一样返 500."
    ),
    responses={
        403: {"description": "非平台管理员"},
        422: {"description": "模板字段校验失败 (default_image 不在 allowed_images / 资源规格越界等)"},
        500: {"description": "K8s 创建 WorkspaceTemplate 失败 (含同名已存在)"},
    },
)
async def admin_create_template_endpoint(
    payload: TemplateCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return await create_custom_template(k8s, payload)


@router.patch(
    "/admin/dev-instance-templates/{name}/allowed-images",
    response_model=dict,
    summary="[管理员] 更新模板的镜像白名单",
    description=(
        "**仅平台管理员**可用. 覆盖式更新指定 WorkspaceTemplate 的 `allowedImages` 字段.\n\n"
        "- 全量替换语义: 传入即最终列表, 不做增量合并.\n"
        "- 仅对新建的开发机生效, 已运行实例不受影响.\n"
        "- 幂等: 反复提交同一列表结果一致.\n"
        "- 模板不存在不映射成 404: K8s 报错统一返 500."
    ),
    responses={
        403: {"description": "非平台管理员"},
        422: {"description": "镜像列表格式不合法 (空列表 / 超 32 项)"},
        500: {"description": "K8s patch WorkspaceTemplate 失败 (含模板不存在)"},
    },
)
async def admin_patch_template_images_endpoint(
    name: str,
    payload: TemplatePatchAllowedImages,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return await patch_template_allowed_images(k8s, name, payload)


@router.delete(
    "/admin/dev-instance-templates/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[管理员] 删除自定义 WorkspaceTemplate",
    description=(
        "**仅平台管理员**可用. 删除自定义 WorkspaceTemplate.\n\n"
        "- **系统内置模板不可删** (`sagemaker-jupyter-template` / "
        "`sagemaker-code-editor-template`, Helm 自管), orchestration 层直接抛 **403**.\n"
        "- **幂等**: 模板不存在 (K8s 404) 视为已删, 返 204.\n"
        "- 不影响已经用该模板起的开发机 (已下发的 Workspace CR 独立)."
    ),
    responses={
        403: {"description": "非平台管理员; 或试图删除系统内置模板"},
        500: {"description": "K8s 删除 WorkspaceTemplate 失败 (404 已按幂等吞掉)"},
    },
)
async def admin_delete_template_endpoint(
    name: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    if not current_user.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    await delete_custom_template(k8s, name)


@router.get(
    "/dev-instance-templates",
    response_model=list[TemplateInfo],
    summary="列出可用的 WorkspaceTemplate",
    description=(
        "返回全部可用 WorkspaceTemplate (系统内置 + 自定义), 供创建开发机时选择镜像/规格.\n\n"
        "- **不做 ws 过滤**: 平台级模板对所有用户可见.\n"
        "- 直接 list K8s CR (workspace.jupyter.org), K8s 异常返 502."
    ),
    responses={
        502: {"description": "K8s API 异常, 无法列 WorkspaceTemplate"},
    },
)
async def list_templates_endpoint(
    k8s: K8sClient = Depends(get_k8s_client),
) -> list[TemplateInfo]:
    try:
        return await list_templates(k8s)
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"k8s api error: {exc.message}",
        ) from exc


# ===== CRUD =====

@router.get(
    "/workspaces/{ws_id}/dev-instances",
    response_model=list[DevInstanceListItem],
    summary="列出工作空间下的开发机",
    description=(
        "按创建者过滤:\n"
        "- `scope=mine` (默认): 当前用户创建的 **∪ 通过 sharing 分享给他的** 开发机\n"
        "- `scope=all`: 返回全 ws 所有开发机 · **需 ws 管理员或平台管理员**\n\n"
        "`phase` 可选, **对 DDB 里的 phase 串精确匹配**. 该串 = Workspace CR 所有 "
        "`status=True` 的 condition type 用 `/` 拼接 (如 `Progressing`, `Available`, "
        "`Available/DirectSSHReady`), 所以模糊状态请前端自己按子串筛, 不要指望此参数.\n\n"
        "**纯读 DDB** — informer 实时维护 phase/started_at, 请求时不触发 K8s sync, "
        "也不做任何后台补偿 (平台已切 directSSH, 原 SSM 注册兜底全线停用)."
    ),
    responses={
        403: {"description": "非 ws 成员; 或 scope=all 但非 ws/平台管理员"},
    },
)
async def list_dev_instances_endpoint(
    ws_id: str,
    phase: str | None = Query(default=None),
    scope: Literal["mine", "all"] = Query(
        default="mine",
        description="mine=仅当前用户创建; all=全部(需管理员)",
    ),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[DevInstanceListItem]:
    # 非 ws 成员一律 403 (越权修复 2026-06-14), 不再泄露 ws 是否存在。
    await assert_ws_member(ws_id, current_user)
    if scope == "all":
        from app.core.security import is_ws_admin
        if not await is_ws_admin(ws_id, current_user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "scope=all requires workspace admin or platform admin; use scope=mine",
            )
        creator_filter: Any = None
    else:
        creator_filter = current_user.get("user_id") or current_user.get("id")

    rows = await crud.list_by_workspace(
        None, ws_id, phase=phase, creator_user_id=creator_filter
    )
    if not rows:
        return []

    # SSM 注册兜底不再在列表触发: 后端 ssm_recovery_sweep (10min 定时) 已兜住
    # "无人访问 → 永久卡 Progressing" 的洞; 详情页 GET 仍即时触发 maybe_recover_ssm。
    # 列表页去掉可避免高频轮询 (30s + 超管双请求) 的重复扫描。

    # 纯读 DDB (A4): informer 实时维护 phase/started_at, 不再请求时 sync K8s。
    # 不再查 workspace: 列表/详情前端都不用 workspace_display_name (列表页自己维护 ws 名)。
    return list(
        await asyncio.gather(*(build_list_item(None, r) for r in rows))
    )


@router.post(
    "/workspaces/{ws_id}/dev-instances",
    response_model=DevInstanceDetail,
    status_code=status.HTTP_201_CREATED,
    summary="创建开发机",
    description=(
        "在 ws 下创建一个开发机 (SageMaker Spaces add-on 的 `Workspace` CR):\n"
        "1. 校验 ws 存在 → 模板 / 镜像白名单 (模板 `allowCustomImages=true` 时放开任意镜像)\n"
        "2. 校验机型: 传 `pool` 时展开成该池全部机型; 传 `instance_type` 时校验 ∈ ws "
        "ComputeQuota 已分配机型 (不在 → 403)\n"
        "3. 校验挂载: `mount_path` / `pvc_name` 必须与该用户 `MountPermissions` (或 ws S3 挂载) "
        "一致, 且 PVC 在集群中真实存在\n"
        "4. 落 DDB (`phase=Creating`, `desired_status=Running`)\n"
        "5. 提交 K8s `Workspace` CR (workspace.jupyter.org), operator 接手 provision Pod / "
        "PVC / directSSH Service; 失败回滚 DDB 行\n\n"
        "创建成功即返 `phase=Creating`; 后续状态由 informer 推进. "
        "**平台已切 directSSH**, 创建流不再做任何 SSM 注册 —— 连接信息由 add-on 建的 "
        "`ssh-<name>` Service + external-dns 提供, 见 `GET /dev-instances/{id}/access-info`.\n\n"
        "**同名不冲突**: CR 名 = `sanitize(name)` + 10 位随机后缀, DDB 主键是 uuid, "
        "同名开发机可共存 (不会 409)."
    ),
    responses={
        400: {"description": "模板不存在 / 镜像不在 allowedImages / mount_path 未授权 / "
                             "pvc_name 不匹配 / pool 下无可用机型"},
        403: {"description": "非 ws 成员或超管; 或 instance_type 不在 ws 配额机型内"},
        404: {"description": "Workspace 不存在"},
        409: {"description": "勾选挂载的 PVC 在集群中不存在 (需先在工作空间重新挂载)"},
        422: {"description": "请求体字段校验失败 (name 格式 / 资源规格越界 / mountPath 非法等)"},
        500: {"description": "K8s 创建 Workspace CR 失败 (DDB 行已回滚)"},
        502: {"description": "校验挂载 PVC 时 K8s API 异常"},
    },
)
async def create_dev_instance_endpoint(
    ws_id: str,
    payload: DevInstanceCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DevInstanceDetail:
    # 仅 ws 成员或超管可在此 ws 起开发机 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    row = await create_dev_instance_flow(
        None, k8s, hp, ws_id, payload, current_user
    )
    return await build_detail(None, row, conditions=[])


@router.get(
    "/dev-instances/{id}",
    response_model=DevInstanceDetail,
    summary="查询开发机详情",
    description=(
        "读取指定开发机的详情. 与列表接口不同, **本接口会即时 sync K8s 并回写 DDB**:\n"
        "- 拉最新 `Workspace.status.conditions` 用于详情页时间线, 同时把 phase / "
        "`access_url` / `last_condition_message` / `last_sync_at` **持久化到 DDB** "
        "(`sync_from_k8s(persist=True)`)\n"
        "- CR 已不存在 (K8s 404) → phase 落 `Terminating` 并落库\n"
        "- 其他 K8s 异常忽略, 仅记 info 日志 (直接用 DDB 里的降级数据)\n\n"
        "**遗留 SSM 兜底** (`maybe_recover_ssm`): 平台已切 directSSH, 正常不会触发 —— "
        "只有存量实例同时满足 \"卡非 Available 且创建超 15min 且 Pod 里存在 running "
        "但 not-ready 的 `ssm-agent-sidecar`\" 时才后台补一次注册 (fire-and-forget, 不阻塞响应)."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
    },
)
async def get_dev_instance_endpoint(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DevInstanceDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    # 仅该 dev instance 所属 ws 的成员或超管可看 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    conditions: list[dict[str, Any]] = []
    try:
        row, conditions = await sync_from_k8s(None, k8s, row)
    except Exception as exc:  # noqa: BLE001
        logger.info("dev_instance.get.sync_skip", id=str(id), err=str(exc))
    # 兜底: 创建期 SSM 注册若超时放弃 (资源紧张 sidecar 没及时 running), 详情页
    # 读取时若满足"卡 Progressing 超 15min 且 sidecar 现已 running 且未注册成功",
    # 后台补触发一次注册 (fire-and-forget, 不阻塞本次响应)。
    try:
        await maybe_recover_ssm(k8s, row)
    except Exception as exc:  # noqa: BLE001
        logger.info("dev_instance.get.ssm_recover_skip", id=str(id), err=str(exc))
    return await build_detail(None, row, conditions=conditions)


@router.get(
    "/dev-instances/{id}/status-detail",
    summary="查询开发机原始 status detail",
    description=(
        "按需单查 `status_detail` 全量 JSON (含 K8s 原始 conditions/events), 详情页 debug 弹窗用. "
        "**纯读 DDB, 不触发 sync**, 保持轻量."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
    },
)
async def get_dev_instance_status_detail(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return {"status_detail": row.get("status_detail")}


@router.get(
    "/dev-instances/{id}/kueue-detail",
    summary="查询开发机 Kueue Workload 实时详情",
    description=(
        "实时查该开发机背后的 Kueue Workload (`conditions` + `admission`), **不落库**.\n\n"
        "开发机走 2 跳: 最新 Pod (`workspace-name` label) uid → Workload. "
        "找不到 Pod 或 Workload 时返 `conditions=[]` / `admission={}` (K8s 异常静默忽略)."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
    },
)
async def get_dev_instance_kueue_detail(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # 开发机 2 跳: 最新 Pod (workspace-name label) uid → Workload。实时查, 不落库。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    ns = row.get("k8s_namespace") or ""
    name = row.get("k8s_workspace_name") or ""
    conditions: list[dict[str, Any]] = []
    admission: dict[str, Any] = {}
    if ns and name:
        try:
            pods = await k8s.list_pods_by_workspace(ns, name)
            pod = pick_latest_pod(pods)
            if pod is not None:
                pod_uid = (pod.get("metadata") or {}).get("uid") or ""
                wls = await k8s.list_workloads_by_job_uid(ns, pod_uid)
                wl_status = (pick_latest_pod(wls) or {}).get("status") or {}
                conditions = wl_status.get("conditions") or []
                admission = wl_status.get("admission") or {}
        except Exception as exc:
            logger.info("dev_instance.kueue_detail.skip", id=str(id), err=str(exc))
    return {"conditions": conditions, "admission": admission}


@router.put(
    "/dev-instances/{id}",
    response_model=DevInstanceDetail,
    summary="更新开发机元数据",
    description=(
        "更新开发机在 DDB 里的元数据: `display_name` / `description` / `env` (三者均可选, "
        "只更新传了的字段).\n\n"
        "- ⚠️ **纯 DDB 元数据更新, 不下发 K8s**: `env` 只存进 DDB (`env_json`) 用于展示/克隆, "
        "**不会 patch Workspace CR**, 因此对当前 Pod 与后续 stop/start 重启后的 Pod "
        "**都不生效**. 想改环境变量只能删除重建.\n"
        "- 不重启开发机, 不改镜像 / 资源规格 / 挂载等结构性字段 (需删除重建)\n"
        "- 幂等: 反复 PUT 同一 payload 结果一致\n"
        "- 权限: 该实例所属 ws 的成员或平台超管即可改 (**不限创建者本人**)"
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
        422: {"description": "字段校验失败"},
    },
)
async def update_dev_instance_endpoint(
    id: str,  # noqa: A002
    payload: DevInstanceUpdate,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DevInstanceDetail:
    # 改前先校验调用者是该实例所属 ws 的成员/超管 (越权修复 2026-06-14):
    # 原端点连 current_user 都没有, 知道 id 即可改别人的开发机。
    existing = await crud.get(None, id)
    if existing is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    await assert_ws_member(str(existing.get("workspace_id")), current_user)
    row = await update_flow(None, k8s, id, payload)
    return await build_detail(None, row)


@router.patch(
    "/dev-instances/{id}/resize",
    response_model=DevInstanceDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="修改开发机规格 (CPU/内存/GPU/EFA + 资源池)",
    description=(
        "改开发机资源规格并下发 K8s (**与改元数据的 PUT 不同, 本接口会 patch Workspace CR**):\n\n"
        "- merge-patch `Workspace.spec.resources` (CPU/内存/GPU/EFA); 传 `pool` 时"
        "额外展开该池全部机型重算 `spec.affinity` (nodeAffinity), 不传则保留原机型约束\n"
        "- **不碰存储**: 主存储 storage class 未开 `allowVolumeExpansion`, EBS 不能扩; "
        "只 patch resources/affinity → PVC 不动 → `/home/sagemaker-user` 数据保留\n"
        "- ⚠️ **运行中改会重建 Pod** (operator 滚新 Pod), 当前会话/终端会中断, "
        "复用同块 EBS, `/home/sagemaker-user` 不丢; Pod 内存态数据不保留\n"
        "- 202 Accepted: patch 后立即读的 DDB 行 (资源已更新, phase 由 informer 推进)\n"
        "- 同步 DDB: `cpu_request_millicores` / `memory_request_mib` / `gpu_count` / "
        "`efa_count` (+ 换池时 `metadata.pool`)\n"
        "- **幂等**: 反复提交同一 payload 结果一致\n"
        "- 权限: **创建者本人 / ws 管理员 / 平台超管**"
    ),
    responses={
        400: {"description": "pool 下无可用机型 (检查 ComputeQuota 分配)"},
        403: {"description": "非创建者本人, 且非 ws 管理员 / 平台超管"},
        404: {"description": "开发机不存在"},
        422: {"description": "资源规格越界"},
        500: {"description": "K8s patch Workspace 失败"},
    },
)
async def resize_dev_instance_endpoint(
    id: str,  # noqa: A002
    payload: DevInstanceResize,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DevInstanceDetail:
    row = await resize_flow(None, k8s, hp, id, payload, current_user)
    return await build_detail(None, row)


@router.post(
    "/dev-instances/{id}/stop",
    response_model=DevInstanceDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="停止开发机",
    description=(
        "停止开发机 (释放算力 + 停计费), 保留 DDB 行与 EBS / 挂载卷, 可后续 start 复用.\n\n"
        "- 202 Accepted: merge-patch K8s `Workspace.spec.desiredStatus = \"Stopped\"`, "
        "phase 由 operator/informer 推进到含 `Stopped`; 响应体是 patch 后立即读的 DDB 行 "
        "(`desired_status=Stopped`, phase 可能还是旧值)\n"
        "- 同时落 DDB: `stopped_at`, 并清空 `started_at` / `ssm_managed_id`\n"
        "- directSSH 无需注销: 连接靠固定 DNS, 停启不变; 存量行若残留 `mi-xxx` 会顺手 "
        "SSM deregister\n"
        "- **幂等**: 已 Stopped 再 stop 无副作用\n"
        "- 权限: **创建者本人 / ws 管理员 / 平台超管**"
    ),
    responses={
        403: {"description": "非创建者本人, 且非 ws 管理员 / 平台超管"},
        404: {"description": "开发机不存在"},
        500: {"description": "K8s patch Workspace 失败"},
    },
)
async def stop_dev_instance_endpoint(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DevInstanceDetail:
    row = await stop_flow(None, k8s, id, current_user)
    return await build_detail(None, row)


@router.post(
    "/dev-instances/{id}/start",
    response_model=DevInstanceDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="启动已停止的开发机",
    description=(
        "启动已 Stopped 的开发机: merge-patch K8s `Workspace.spec.desiredStatus = \"Running\"`, "
        "operator 重新 provision Pod.\n\n"
        "- 202 Accepted: 只落 `desired_status=Running` 到 DDB, phase 由 informer 推进 "
        "(`Progressing → Available`)\n"
        "- **幂等**: 已 Running 再 start 无副作用\n"
        "- 复用原 EBS / 挂载; Pod IP 与 Pod 内存态数据不保留\n"
        "- directSSH: add-on 会重建 `ssh-<name>` Service, external-dns 同步同一固定 DNS 名, "
        "**平台侧无任何注册动作** (SSH 连接命令不变)\n"
        "- 权限: **创建者本人 / ws 管理员 / 平台超管**"
    ),
    responses={
        403: {"description": "非创建者本人, 且非 ws 管理员 / 平台超管"},
        404: {"description": "开发机不存在"},
        500: {"description": "K8s patch Workspace 失败"},
    },
)
async def start_dev_instance_endpoint(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> DevInstanceDetail:
    row = await start_flow(None, k8s, id, current_user)
    return await build_detail(None, row)


@router.delete(
    "/dev-instances/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除开发机",
    description=(
        "删 K8s `Workspace` CR (workspace.jupyter.org), operator finalizer 级联回收 Pod / "
        "EBS / directSSH Service; 挂载的共享 FSx/S3 PVC 本身不删.\n\n"
        "- DDB 行 **软删** (打 `deleted_at` + `kueue_status=finished`, 移出活跃 GSI), "
        "列表不再返回, 审计仍可查; 不硬删\n"
        "- 顺带清理该实例在本 ws 的 sharing 记录 (best-effort, 失败不阻塞)\n"
        "- 存量行若残留 `ssm_managed_id` 会顺手 SSM deregister (directSSH 下恒为空)\n"
        "- **幂等**: CR 已不在 (K8s 404) 按已删处理, 返 204\n"
        "- 不保留任何 Pod 内 / EBS 上的数据 (需提前存到共享挂载卷)\n"
        "- 权限: **创建者本人 / ws 管理员 / 平台超管**"
    ),
    responses={
        403: {"description": "非创建者本人, 且非 ws 管理员 / 平台超管"},
        404: {"description": "开发机不存在 (DDB 无此 id)"},
        500: {"description": "K8s 删除 Workspace 失败 (404 已按幂等吞掉)"},
    },
)
async def delete_dev_instance_endpoint(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    await delete_flow(None, k8s, id, current_user)
    return None


@router.get(
    "/dev-instances/{id}/access-info",
    response_model=AccessInfo,
    summary="获取开发机 directSSH 接入信息",
    description=(
        "返回 **directSSH** 连接信息 (本地终端 / VSCode Remote-SSH 用). 平台已不再用 "
        "SSM Session Manager.\n\n"
        "- `ssh_hostname`: 从 add-on 建的 `ssh-<workspace_name>` Service 上的 external-dns "
        "注解 (`external-dns.alpha.kubernetes.io/hostname`) 实时读回的固定 DNS 名 "
        "(VPC 内私有 zone, 停启不变). Service / 注解还没建好时为 `null`\n"
        "- `ssh_port` 恒 `22222`, `ssh_user` 恒 `sagemaker-user`; 另给 `ssh_command` "
        "一行命令与 `ssh_config_snippet` (无 ProxyCommand)\n"
        "- 鉴权走 **公钥**: 用户需先在 code editor / JupyterLab 里把自己的公钥追加到 "
        "开发机的 `~/.ssh/authorized_keys` (`notes` 里也会提示)\n"
        "- `ssm_managed_id` / `ssm_command` 为兼容老前端保留, **恒为 `null`**\n"
        "- **敏感**: 拿到即开发机 shell 入口, 仅 ws 成员/超管可读\n"
        "- 会即时 sync 一次 K8s 并**回写 DDB** (与详情接口同一 `sync_from_k8s`); "
        "K8s 异常静默降级用 DDB 数据"
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
    },
)
async def access_info_endpoint(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> AccessInfo:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    # access-info 含 directSSH 连接信息 (shell 入口), 仅成员/超管可拿 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    try:
        row, _ = await sync_from_k8s(None, k8s, row)
    except Exception as exc:  # noqa: BLE001
        logger.info("dev_instance.access.sync_skip", err=str(exc))
    return await build_access_info(row, k8s)


@router.post(
    "/dev-instances/{id}/authorized-keys",
    response_model=AuthorizedKeyResult,
    summary="写入 SSH 公钥到开发机 authorized_keys",
    description=(
        "把调用者的 SSH **公钥**追加到开发机的 `~/.ssh/authorized_keys` (幂等, 整行去重), "
        "替代手动打开 code editor 终端粘命令的步骤。\n\n"
        "- 平台代执行 (`exec` 进主容器 `workspace`): `mkdir -p ~/.ssh` → `chmod 700` → "
        "整行去重追加 → `chmod 600`\n"
        "- 公钥经 argv 传入容器 (不拼进 shell 脚本文本), 无注入风险; 只接受合法 OpenSSH "
        "公钥格式 (拒绝私钥/换行/垃圾)\n"
        "- 开发机必须在运行 (Pod `Running`), 否则 400\n"
        "- 权限: **创建者本人 / 平台超管 / 被创建者分享的人** (与能否打开 code editor 一致)"
    ),
    responses={
        400: {"description": "开发机未运行 (Pod 未就绪)"},
        403: {"description": "非创建者本人 / 超管 / 被分享者"},
        404: {"description": "开发机不存在"},
        422: {"description": "公钥格式非法"},
        500: {"description": "容器内写入失败"},
    },
)
async def add_authorized_key_endpoint(
    id: str,  # noqa: A002
    payload: AuthorizedKeyAdd,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> AuthorizedKeyResult:
    result = await add_authorized_key_flow(k8s, id, payload.public_key, current_user)
    return AuthorizedKeyResult(**result)


@router.post(
    "/dev-instances/{id}/ssm-init",
    response_model=AccessInfo,
    summary="[遗留] 手动重试 SSM sidecar 注册",
    description=(
        "⚠️ **遗留接口, 新开发机不需要**: 平台已切 directSSH, 创建流不再做 SSM 注册, "
        "接入信息见 `GET /dev-instances/{id}/access-info`.\n\n"
        "仍保留的行为: 等 `ssm-agent-sidecar` 容器 running (最长 10min) → "
        "`ssm:CreateActivation` → exec sidecar 跑 `register-ssm.sh` (最多 3 次) → "
        "在主容器起 remote-access-server → 读回 `mi-xxx` 写 DDB "
        "(`ssm_managed_id` + `ssm_init_status=done`).\n\n"
        "- 无 SSM sidecar 的开发机 (directSSH 形态) 调用会在等待 sidecar 处超时, "
        "只把 `ssm_init_status` 写成 `failed`, HTTP 仍返 200\n"
        "- 响应体是 directSSH 的 `AccessInfo` (其中 `ssm_managed_id` 字段恒 `null`)\n"
        "- 幂等: 重复调用只是覆盖注册结果\n"
        "- 权限: **只要求已登录, 不校验 ws 成员**"
    ),
    responses={
        404: {"description": "开发机不存在"},
    },
)
async def ssm_init_endpoint(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
) -> AccessInfo:
    """[遗留] 主动给 sidecar 注入 SSM activation 拿 mi-xxx 写回 DDB.

    平台已切 directSSH, 创建流不再自动注册 (create.py _post_create_ssm_init
    已停用), 本入口只对残留 SSM sidecar 形态的开发机有意义。
    """
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    mi = await register_ssm_in_sidecar(k8s, row)
    if mi:
        row["ssm_managed_id"] = mi
        row["ssm_init_status"] = "done"
    else:
        row["ssm_init_status"] = "failed"
    await crud.update(None, row)
    return await build_access_info(row, k8s)


# ===== HTTP 代理 (浏览器开 JupyterLab/Code Editor) =====
# 后端跟开发机 Pod 在同一 EKS 集群时, 浏览器通过此代理访问主容器 :8888 的
# JupyterLab/Code-Editor Web UI. 三层目标解析见 _resolve_proxy_target.
# 普通 HTTP 走下面的 GET/POST/... handler; WebSocket (Code Editor 初始化 / kernel)
# 走文件末尾的 proxy_jupyter_ws (双向转发)。

_EXCLUDE_REQ_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "origin",
    "referer",
}
_EXCLUDE_RESP_HEADERS = {
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
}


async def _resolve_proxy_target(
    k8s: K8sClient, row: dict[str, Any], path: str
) -> str:
    """3 层目标解析 (覆盖部署形态):
    1) settings.dev_proxy_local_target  - 本地 mac kubectl port-forward
    2) KUBERNETES_SERVICE_HOST 在 + 非跨集群 - 后端与开发机同集群, 走 service DNS
    3) podIP fallback                    - 后端在外 / 跨集群 + 路由打通时
    """
    import os
    from app.core.config import get_settings

    settings = get_settings()

    local_target = (settings.dev_proxy_local_target or "").strip()
    if local_target:
        return f"http://{local_target}/{path}"

    ns = row["k8s_namespace"]
    ws_name = row["k8s_workspace_name"]

    # 跨集群: 平台集群跟开发机(业务集群)不同集群, .svc.cluster.local 解析不到
    # 业务集群 service → 跳过 DNS 分支, 直接走 podIP (podIP 同 VPC 可达).
    if os.environ.get("KUBERNETES_SERVICE_HOST") and not settings.cross_cluster_mode:
        # 后端跑在 EKS Pod 内, kube-dns 能解析 .svc.cluster.local
        try:
            ws_cr = await k8s.get_workspace(ns, ws_name)
        except Exception:  # noqa: BLE001
            ws_cr = {}
        svc_name = ((ws_cr.get("status") or {}).get("serviceName")
                    or f"workspace-{ws_name}-service")
        svc_host = f"{svc_name}.{ns}.svc.cluster.local"
        return f"http://{svc_host}:8888/{path}"

    # podIP fallback
    pod = await k8s.get_pod_by_workspace(ns, ws_name)
    if not pod:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "pod not found"
        )
    pod_ip = (pod.get("status") or {}).get("podIP") or (
        pod.get("status") or {}
    ).get("pod_ip")
    if not pod_ip:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "pod has no IP yet"
        )
    return f"http://{pod_ip}:8888/{path}"


def _proxy_blocked_phase(phase: str | None) -> bool:
    """代理 gate 负向判定: phase 含 Stopped 或 Terminating → 挡 (实例已停/删除中)。

    其余 (含 Available 运行中、空串/启动中) 一律放行 —— "还没起来" 由下游
    _resolve_proxy_target 的 service-DNS / pod-IP 检查返 503 自然把守。
    不正向判 Available: 避免误挡 "sidecar 拖累 Available 但主容器可用" 的过渡态实例。
    """
    p = phase or ""
    return "Stopped" in p or "Terminating" in p


async def _proxy_jupyter_impl(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient,
) -> Response:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    if _proxy_blocked_phase(row.get("phase")):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"dev instance not available (phase={row.get('phase')})",
        )

    # JupyterLab 设了 --ServerApp.base_url=/api/v1/dev-instances/{id}/proxy/,
    # 它只认带完整前缀的路径 (裸 /lab 会 404)。转发时把前缀加回去。
    # code-editor 不设 base_url, 走裸 path。
    upstream_path = path
    if row.get("app_type") == "jupyterlab":
        upstream_path = f"api/v1/dev-instances/{id}/proxy/{path}"

    target_url = await _resolve_proxy_target(k8s, row, upstream_path)
    qs = request.url.query
    if qs:
        target_url = f"{target_url}?{qs}"

    fwd_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _EXCLUDE_REQ_HEADERS
    }
    body = await request.body()

    try:
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=False
        ) as client:
            upstream = await client.request(
                method=request.method,
                url=target_url,
                headers=fwd_headers,
                content=body if body else None,
            )
    except httpx.RequestError as exc:
        logger.warning(
            "dev_instance.proxy.upstream_err",
            id=str(id),
            url=target_url,
            err=str(exc),
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"upstream error: {exc}"
        ) from exc

    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _EXCLUDE_RESP_HEADERS
    }

    # ── 重定向改写: JupyterLab 302 Location 路径修正 ──
    # JupyterLab 按自身 JUPYTER_BASE_URL 生成重定向 (如 /lab, /workspaces/...),
    # 但浏览器访问的是 /api/v1/dev-instances/{id}/proxy/... 路径.
    # 把绝对路径重定向改为 proxy 前缀下的相对路径.
    if upstream.status_code in (301, 302, 303, 307, 308):
        location = resp_headers.get("location", "")
        if location and location.startswith("/"):
            # 绝对路径 → 加 proxy 前缀
            proxy_prefix = f"/api/v1/dev-instances/{id}/proxy"
            if not location.startswith(proxy_prefix):
                resp_headers["location"] = f"{proxy_prefix}{location}"

    # ── WebSocket rewrite: 把 remoteAuthority 从 pod IP 改为外部 proxy 路径 ──
    # Code Editor 前端 JS 从 HTML <meta> 的 remoteAuthority 读取 WS 目标,
    # 如果是 pod 内网 IP, 浏览器无法通过 CloudFront 访问. 替换为当前请求
    # 的 Host (即 example.com), 让 WS 也走 CloudFront → VPC Origin → ALB → 后端 proxy.
    # JupyterLab 的 baseUrl 不在这里改: 改用创建时注入 WORKSPACE_BASE_URL
    # (--ServerApp.base_url), 让 JupyterLab 启动就带 proxy 前缀, config 里 20+ 个
    # *Url 字段从源头都带前缀 (HTML rewrite 逐个替换会漏字段导致白屏)。
    content = upstream.content
    content_type = upstream.headers.get("content-type", "")
    if "text/html" in content_type and b"remoteAuthority" in content:
        from urllib.parse import urlparse
        # 从 target_url 提取 pod_ip:port
        parsed = urlparse(target_url)
        pod_ip = parsed.hostname
        # remoteAuthority 只需是 host(:port), VS Code 自动从页面 URL 继承 path
        # 把 pod_ip:任意端口 替换为外部域名 (HTTPS 443 不用写端口)
        external_host = request.headers.get("host", request.url.hostname)
        import re
        pattern = re.escape(pod_ip).encode() + rb":\d+"
        content = re.sub(pattern, external_host.encode(), content)

    resp = Response(
        content=content,
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )

    # 首个导航请求带 ?access_token= 时, 种 cookie 供后续子资源 (css/js, URL 不带
    # query token, 浏览器自动带 cookie) 认证。cookie path 限定到本开发机 proxy 前缀。
    qtoken = request.query_params.get("access_token", "").strip()
    if qtoken:
        resp.set_cookie(
            key="dev_proxy_token",
            value=qtoken,
            path=f"/api/v1/dev-instances/{id}/proxy",
            httponly=True,
            samesite="lax",
            max_age=3600,
        )
    return resp


_PROXY_PATH = "/dev-instances/{id}/proxy/{path:path}"
_PROXY_SUMMARY = "浏览器代理访问开发机 JupyterLab / Code Editor"  # i18n-exempt: openapi
_PROXY_DESCRIPTION = (  # i18n-exempt: openapi
    "把浏览器请求代理到开发机主容器 :8888 的 JupyterLab / Code-Editor Web UI, "
    "所有 HTTP 方法 (GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS) 共用同一实现.\n\n"
    "**目标解析** (三层 fallback, 见 `_resolve_proxy_target`):\n"
    "1. `settings.dev_proxy_local_target` — 本地 mac `kubectl port-forward` 调试模式\n"
    "2. 同集群 (`KUBERNETES_SERVICE_HOST` 且非跨集群) — 走 service DNS `.svc.cluster.local`\n"
    "3. 跨集群 / 后端在外 — 直接连 Pod IP (需 VPC 打通)\n\n"
    "**路径改写**: JupyterLab 设了 `--ServerApp.base_url=/api/v1/dev-instances/{id}/proxy/`, "
    "上游只认带前缀的路径, 转发时会加回去; code-editor 不设 base_url 走裸 path.\n\n"
    "**重定向 / HTML 改写**: 3xx `Location` 加上 proxy 前缀; Code Editor HTML 里的 "
    "`remoteAuthority` (pod IP) 替换为当前请求 Host, 让 WS 也能走 CloudFront → 后端 proxy.\n\n"
    "**Cookie 兜底**: 首次带 `?access_token=` 的导航请求会种 `dev_proxy_token` cookie "
    "(path 限本开发机 proxy), 供后续无 query token 的子资源 (css/js) 认证.\n\n"
    "**gate**: phase 含 `Stopped` / `Terminating` → 409; Pod 没有 / 还没拿到 IP → 503; "
    "上游 (Pod / service) 连不上或超时 → 502. 其余 phase (含空串/启动中) 一律放行.\n\n"
    "**鉴权**: 由 AuthMiddleware 统一处理, 除 `Authorization: Bearer` 外还接受 "
    "`?access_token=` query 与 `dev_proxy_token` cookie (浏览器子资源用); "
    "**本路由不再额外校验 ws 成员**.\n\n"
    "WebSocket (Code Editor 初始化 / JupyterLab kernel) 走独立的 `/proxy/{path:path}` websocket 路由."
)
_PROXY_RESPONSES = {  # i18n-exempt: openapi
    404: {"description": "开发机不存在"},
    409: {"description": "开发机已 Stopped / Terminating, 代理已关"},
    502: {"description": "上游 (Pod / service) 请求异常"},
    503: {"description": "Pod 未就绪 (无 IP / 未起来)"},
}


@router.get(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_get(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


@router.post(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_post(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


@router.put(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_put(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


@router.delete(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_delete(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


@router.patch(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_patch(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


@router.head(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_head(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


@router.options(
    _PROXY_PATH,
    summary=_PROXY_SUMMARY,
    description=_PROXY_DESCRIPTION,
    responses=_PROXY_RESPONSES,
)
async def proxy_jupyter_options(
    id: str,  # noqa: A002
    path: str,
    request: Request,
    k8s: K8sClient = Depends(get_k8s_client),
) -> Response:
    return await _proxy_jupyter_impl(id, path, request, k8s)


# ===== WebSocket proxy (Code Editor / JupyterLab kernel 等长连接) =====
# Code Editor (code-server) 首页加载即建 WS 初始化 IDE, 普通 HTTP proxy 转不了 WS,
# 故单独一个 websocket 路由做双向转发。
#
# ⚠️ 鉴权: BaseHTTPMiddleware (AuthMiddleware) 不拦 websocket scope, 所以这里
#    必须自己验 ?access_token= (跟 HTTP proxy 的 query token 机制一致)。

async def _ws_pump(src: Any, send_text: Any, send_bytes: Any) -> None:
    """从 src (一端) 读消息, 用 send_text/send_bytes 转发到另一端, 直到任一端关闭。"""
    async for message in src:
        if isinstance(message, (bytes, bytearray)):
            await send_bytes(bytes(message))
        else:
            await send_text(message)


@router.websocket("/dev-instances/{id}/proxy/{path:path}")
async def proxy_jupyter_ws(
    websocket: WebSocket,
    id: str,  # noqa: A002
    path: str,
    k8s: K8sClient = Depends(get_k8s_client),
) -> None:
    import websockets
    from app.core.config import get_settings
    from app.core.cognito_jwt import verify_cognito_id_token

    settings = get_settings()

    # 1) 鉴权: 验 token (middleware 不拦 WS, 必须自己验)。
    #    优先 query 的 access_token; 没有则取 cookie dev_proxy_token (Code Editor 的
    #    WS 握手是浏览器自动发起, URL 常不带 query token, 靠 HTTP proxy 首次种的 cookie)。
    token = (
        websocket.query_params.get("access_token", "").strip()
        or websocket.cookies.get("dev_proxy_token", "").strip()
    )
    if not token:
        await websocket.close(code=4401)  # 4401: 自定义 "unauthorized"
        return
    try:
        verify_cognito_id_token(token, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("dev_instance.proxy.ws_auth_fail", id=str(id), err=str(exc))
        await websocket.close(code=4401)
        return

    # 2) 解析 upstream 目标 (复用 HTTP proxy 的三层解析), http scheme → ws scheme。
    #    upstream 是集群内开发机 pod 的明文连接 (pod 不跑 TLS), 走 VPC 东西向,
    #    不面向公网; 浏览器侧那段独立走 ALB/SSM 的加密连接。故此处明文是必然且安全。
    row = await crud.get(None, id)
    if row is None or _proxy_blocked_phase(row.get("phase")):
        await websocket.close(code=4404)
        return
    # JupyterLab base_url 带前缀, WS (kernel 等) 也要带完整前缀; code-editor 走裸 path。
    upstream_path = path
    if row.get("app_type") == "jupyterlab":
        upstream_path = f"api/v1/dev-instances/{id}/proxy/{path}"
    http_target = await _resolve_proxy_target(k8s, row, upstream_path)
    ws_target = http_target.replace("http://", "ws://", 1)  # nosemgrep: detect-insecure-websocket — 集群内 pod upstream 明文, 非公网, 见上方注释
    # 透传 query (含 code-server 需要的参数; access_token 一并带过去无害)
    qs = websocket.url.query
    if qs:
        ws_target = f"{ws_target}?{qs}"

    # 3) 接受浏览器侧 WS, 连 upstream, 双向转发。
    #    subprotocols: 把浏览器请求的子协议透传给 upstream (code-server 可能用)。
    sub = websocket.headers.get("sec-websocket-protocol")
    await websocket.accept(subprotocol=(sub.split(",")[0].strip() if sub else None))
    logger.info("dev_instance.proxy.ws_accept", id=str(id), target=ws_target, sub=sub)

    try:
        async with websockets.connect(
            ws_target,
            subprotocols=[s.strip() for s in sub.split(",")] if sub else None,
            max_size=None,          # 不限消息大小 (IDE 传大 payload)
            open_timeout=30,
            ping_interval=None,     # 转发场景不自己发 ping, 交给两端
        ) as upstream:
            logger.info("dev_instance.proxy.ws_upstream_connected", id=str(id))

            async def browser_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            await upstream.close()
                            return
                        if (b := msg.get("bytes")) is not None:
                            await upstream.send(b)
                        elif (t := msg.get("text")) is not None:
                            await upstream.send(t)
                finally:
                    logger.info("dev_instance.proxy.ws_b2u_end", id=str(id))

            async def upstream_to_browser() -> None:
                try:
                    await _ws_pump(
                        upstream, websocket.send_text, websocket.send_bytes
                    )
                finally:
                    logger.info("dev_instance.proxy.ws_u2b_end", id=str(id))

            # 任一方向结束就收尾 (FIRST_COMPLETED), 取消另一方向避免悬挂
            done, pending = await asyncio.wait(
                [asyncio.create_task(browser_to_upstream()),
                 asyncio.create_task(upstream_to_browser())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc:
                    logger.warning(
                        "dev_instance.proxy.ws_pump_err",
                        id=str(id), err=f"{type(exc).__name__}: {exc}",
                    )
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed) as exc:
        logger.info("dev_instance.proxy.ws_closed", id=str(id), err=str(exc)[:120])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dev_instance.proxy.ws_upstream_err",
            id=str(id), target=ws_target, err=f"{type(exc).__name__}: {exc}",
        )
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
