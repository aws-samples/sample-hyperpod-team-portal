"""Workspace + Members HTTP 路由 (DDB-only).

UUID → str (DDB key); db 参数全部移除.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import (
    assert_ws_admin,
    assert_ws_member,
    get_current_user,
    require_admin,
)
from app.adapters.k8s import K8sClient
from app.modules.workspace.api.deps import get_hyperpod_client, get_k8s_client
from app.modules.workspace.domain.visibility import effective_visibility_user_id
from app.modules.workspace.api.schemas import (
    MemberAdd,
    MemberResponse,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceUpdate,
)
from app.modules.workspace.orchestration import (
    add_member_flow,
    create_workspace_flow,
    delete_workspace_flow,
    remove_member_flow,
    update_member_role_flow,
    update_workspace_flow,
)
from app.adapters.aws.identitystore import IdcAPIError, find_user
from app.modules.user.api.router import IdcUserSummary
from app.modules.workspace.persistence import crud
from app.modules.workspace.response import build_workspace_detail, list_members_flow
from app.services.hyperpod_client import HyperPodClient

workspace_router = APIRouter(tags=["workspaces"])


# ===== Workspace CRUD =====

@workspace_router.get(
    "",
    response_model=list[WorkspaceDetail],
    summary="列出工作空间",
    description=(
        "按可见性过滤:\n"
        "- 超管: 返回全平台所有 ws\n"
        "- 普通用户: 仅返回自己 owner + member 的 ws\n\n"
        "可见范围只由已认证身份决定, 不接受前端传的 user_id (越权修复 2026-06-14).\n\n"
        "可选过滤: `status` (按 ws 生命周期状态). "
        "`cluster_id` 参数保留但 **M1 不生效** (cluster_id 未落 DDB, 传了也不过滤).\n\n"
        "**纯读 DDB**, 不请求 K8s / AWS."
    ),
    responses={
        401: {"description": "未登录"},
    },
)
async def list_workspaces_endpoint(
    cluster_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[WorkspaceDetail]:
    # 可见范围只由已认证身份决定, 不信前端传的 user_id (越权修复 2026-06-14):
    #   超管 → 全部 ws; 普通用户 → 仅自己 owner+member 的 ws。
    effective_user_id = effective_visibility_user_id(current_user)
    rows = await crud.list_workspaces(
        None,
        cluster_id=cluster_id,
        user_id=effective_user_id,
        status_filter=status_filter,
    )
    # build_workspace_detail 已经是纯 in-memory (0 await), 不需要 gather.
    return [await build_workspace_detail(None, ws) for ws in rows]


@workspace_router.get(
    "/{ws_id}",
    response_model=WorkspaceDetail,
    summary="查询工作空间详情",
    description=(
        "返回 ws 完整信息: 元数据 (display_name / description / primary_gid) + "
        "关联集群 (cluster_id / cluster_tag) + K8s namespace + `sagemaker_compute_quota_id`.\n\n"
        "`owner_*` 字段已废弃恒空 (ws 无 owner 概念); `quota_summary` 恒为 null, "
        "配额详情请调 `/workspaces/{ws_id}/quota`.\n\n"
        "**权限**: 仅 ws 成员或平台超管可看 (越权修复 2026-06-14).\n\n"
        "**纯读 DDB**, 不请求 K8s / AWS."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace 不存在"},
    },
)
async def get_workspace_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WorkspaceDetail:
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    # 仅 ws 成员或平台超管可看详情 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    return await build_workspace_detail(None, ws)


@workspace_router.post(
    "",
    response_model=WorkspaceDetail,
    status_code=status.HTTP_201_CREATED,
    summary="创建工作空间 · 仅超管",
    description=(
        "级联创建团队隔离所需资源:\n"
        "1. AWS `CreateComputeQuota` (HyperPod 集群配额, 绑定该 ws)\n"
        "2. 轮询等 K8s namespace 出现 (**由 HyperPod taskgovernance add-on 异步 reconcile 出来**, "
        "本端点不建 namespace, 也不建 Kueue LocalQueue; 最多等 30s)\n"
        "3. 在该 namespace 建 `ServiceAccount` (workspace-default) + `Role` + `RoleBinding`\n"
        "4. 建 EKS Pod Identity Association (SA → platform pod role; 未配 role_arn / "
        "cluster_name 时跳过)\n"
        "5. 写 DDB Workspaces 行\n"
        "6. best-effort 把两个系统 WorkspaceTemplate 的 allowedImages seed 进镜像中心 "
        "(失败只 warn, 不回滚)\n\n"
        "**权限**: 仅平台超管. ws owner 记为**当前调用的超管** (payload 无 owner 字段); "
        "`WorkspaceDetail.owner_*` 已废弃恒空, 创建人审计走 AuditLog.\n\n"
        "**非幂等**: 同名 ws / 同 namespace 复建返 409. 失败一律反向回滚已建的 AWS / K8s 资源: "
        "AWS ComputeQuota 失败或 K8s/Pod-Identity 失败返 502, DDB 写失败返 500."
    ),
    responses={
        400: {"description": "Cluster 未绑定 hyperpod_cluster_arn"},
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "Cluster 不存在"},
        409: {"description": "Workspace 名 / namespace 已被占用"},
        422: {"description": "payload 校验失败"},
        500: {"description": "DDB 写入失败 (AWS / K8s 已回滚)"},
        502: {"description": "AWS CreateComputeQuota 失败, 或 K8s / Pod Identity 配置失败 (AWS 已回滚)"},
    },
)
async def create_workspace_endpoint(
    payload: WorkspaceCreate,
    current_user: dict[str, Any] = Depends(require_admin),
    hp_client: HyperPodClient = Depends(get_hyperpod_client),
    k8s_client: K8sClient = Depends(get_k8s_client),
) -> WorkspaceDetail:
    ws = await create_workspace_flow(None, payload, current_user, hp_client, k8s_client)
    return await build_workspace_detail(None, ws)


@workspace_router.put(
    "/{ws_id}",
    response_model=WorkspaceDetail,
    summary="更新工作空间元数据",
    description=(
        "只允许改 `display_name` / `description`, **不能改 name / namespace / cluster_id / quota** "
        "(这些会破坏 K8s / Kueue / ComputeQuota 绑定).\n\n"
        "**权限**: 仅 ws admin 或平台超管 (越权修复 2026-06-14).\n\n"
        "只落 DDB, 不触碰 K8s / AWS. 幂等: 同 payload 重发返相同 detail."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        404: {"description": "Workspace 不存在"},
        422: {"description": "payload 校验失败"},
    },
)
async def update_workspace_endpoint(
    ws_id: str,
    payload: WorkspaceUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WorkspaceDetail:
    # 改 ws 名称/描述属管理操作: 仅 ws admin 或平台超管 (越权修复 2026-06-14)
    await assert_ws_admin(ws_id, current_user)
    ws = await update_workspace_flow(None, ws_id, payload)
    return await build_workspace_detail(None, ws)


@workspace_router.delete(
    "/{ws_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除工作空间 · 仅超管",
    description=(
        "级联清理 (按序, K8s 单项失败只 log 不中断):\n"
        "1. K8s: 删 `metadata_json.fsx_mounts` 里记录的 PVC/PV (注意: **只删 `pvc_name`, "
        "即 rw 那套**; 新版双建的 `pvc_name_rw`/`pvc_name_ro` 与 `s3_mounts` 的 PV/PVC 不删, 会残留) "
        "+ 删 ws `Role` / `RoleBinding` / `ServiceAccount`\n"
        "2. EKS: 删 Pod Identity Association\n"
        "3. AWS: `DeleteComputeQuota` (namespace 与 Kueue queue 由 HyperPod taskgovernance "
        "回收, **本端点不删 namespace**; 实测可能残留)\n"
        "4. DDB: 删成员行 + ws 行\n"
        "5. 写 AuditLog\n\n"
        "**权限**: 仅平台超管.\n\n"
        "**非幂等**: ws 不存在返 404 (AWS 侧 quota 已删则容忍). 仍在跑的任务/推理会随资源回收失败, 慎用."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "Workspace 不存在"},
        502: {"description": "AWS DeleteComputeQuota 失败"},
    },
)
async def delete_workspace_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(require_admin),
    hp_client: HyperPodClient = Depends(get_hyperpod_client),
    k8s_client: K8sClient = Depends(get_k8s_client),
) -> None:
    await delete_workspace_flow(
        None, ws_id, hp_client, current_user, k8s_client
    )
    return None


# ===== Members =====

@workspace_router.get(
    "/{ws_id}/members",
    response_model=list[MemberResponse],
    summary="列出工作空间成员",
    description=(
        "返回 ws 成员列表, 按 `joined_at` 升序. ws 无 owner 概念, "
        "`role` 只有 `admin` | `member` 两种.\n\n"
        "**权限**: 仅 ws 成员或平台超管 (越权修复 2026-06-14).\n\n"
        "**纯读 DDB**."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace 不存在"},
    },
)
async def list_members_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[MemberResponse]:
    # 仅 ws 成员或平台超管可看成员名单 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    return await list_members_flow(None, ws_id)


@workspace_router.get(
    "/{ws_id}/idc/users",
    response_model=list[IdcUserSummary],
    summary="搜索 IdC 用户 (ws 加成员表单用)",
    description=(
        "ws 加成员弹窗搜 IdC 用户: 走 GetUserId **精确等值**, 返 0 或 1 条.\n"
        "- 含 `@` 视作 email\n"
        "- 否则视作 username\n\n"
        "**权限**: 仅 ws admin 或平台超管. 平台级 `/idc/users` 接口是超管专用, 语义相同.\n\n"
        "**只读 IdC**, 不落库."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        502: {"description": "IdC API 调用失败"},
    },
)
async def search_idc_users_for_ws_endpoint(
    ws_id: str,
    q: str = Query(min_length=1, max_length=128, description="完整 username 或 email"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[IdcUserSummary]:
    """ws 管理员加成员搜索 IdC 用户 (ws 级鉴权包装, 原 /idc/users 平台超管接口不变)。

    与平台级 search_idc_users_endpoint 同语义: M1 走 GetUserId 精确等值,
    返 0 或 1 条。含 "@" 视作 email, 否则 username。
    """
    await assert_ws_admin(ws_id, current_user)
    try:
        user = await find_user(q)
    except IdcAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IdC API failed [{exc.code}]: {exc.message}",
        ) from exc

    if user is None:
        return []
    return [
        IdcUserSummary(
            username=user["username"],
            email=user["email"],
            display_name=user["display_name"] or user["username"],
        )
    ]


@workspace_router.post(
    "/{ws_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="添加工作空间成员",
    description=(
        "把一个 IdC 用户加为 ws 成员 (role=`member` 或 `admin`). "
        "上游先用 `/idc/users` 搜到 username, 再调本接口落库. "
        "服务端会再查一次 IdC 拿真 email / display_name 冗余进成员行.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**幂等**: 同 user 重复加**不报错** (ON CONFLICT DO NOTHING), 返 201 + 已有成员记录 "
        "(role 不会被改写, 改角色请用 PUT)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        404: {"description": "Workspace 不存在, 或 IdC 查不到该 username"},
        422: {"description": "payload 校验失败"},
        502: {"description": "IdC API 调用失败"},
    },
)
async def add_member_endpoint(
    ws_id: str,
    payload: MemberAdd,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MemberResponse:
    await assert_ws_admin(ws_id, current_user)
    return await add_member_flow(None, ws_id, payload, current_user)


@workspace_router.put(
    "/{ws_id}/members/{user_id}",
    response_model=MemberResponse,
    summary="更新成员角色",
    description=(
        "改成员 role (`member` ↔ `admin`). ws 无 owner 概念.\n\n"
        "**自降级保护**: ws admin 不能把**自己**降级为 `member` → 403; 平台超管不受此限.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "幂等: 相同 role 重发返当前记录."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管; 或 ws admin 试图把自己降级为 member"},
        404: {"description": "成员关系不存在"},
        422: {"description": "payload 校验失败"},
    },
)
async def update_member_endpoint(
    ws_id: str,
    user_id: str,
    payload: MemberUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MemberResponse:
    await assert_ws_admin(ws_id, current_user)
    return await update_member_role_flow(None, ws_id, user_id, payload.role, current_user)


@workspace_router.delete(
    "/{ws_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="移除工作空间成员",
    description=(
        "从 ws 移除一个成员. ws 无 owner 概念.\n\n"
        "**自移除保护**: ws admin 不能移除**自己** → 403 \"不能移除自己\"; 平台超管不受此限.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**非幂等**: 已不在成员表返 404 (调用方语义清晰). "
        "副作用: 该用户在此 ws 的 FSx grants 一并清理 (清理失败只 warn, 不影响 204)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管; 或 ws admin 试图移除自己"},
        404: {"description": "成员关系不存在"},
    },
)
async def delete_member_endpoint(
    ws_id: str,
    user_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    await assert_ws_admin(ws_id, current_user)
    await remove_member_flow(None, ws_id, user_id, current_user)
    return None
