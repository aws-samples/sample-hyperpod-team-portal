"""Workspace FSx 挂载相关 HTTP 路由.

GET    /api/v1/fsx-filesystems 列候选池 (admin 预建的可用 FSx)
GET    /api/v1/workspaces/{ws_id}/fsx 列已挂的 FSx
POST   /api/v1/workspaces/{ws_id}/fsx 挂载 (建 PV+PVC)
DELETE /api/v1/workspaces/{ws_id}/fsx/{mount_id}      卸载 (按 mount_id, force=true 跳过 pod 占用检查)

"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.adapters.aws.fsx import FsxAPIError, list_managed_filesystems
from app.adapters.k8s import K8sClient
from app.core.logging import get_logger
from app.core.security import assert_ws_admin, assert_ws_member, get_current_user, require_admin
from app.modules.workspace.api.deps import get_k8s_client
from app.modules.workspace.orchestration.fsx import (
    _get_ws_or_404,
    attach_fsx_flow,
    detach_fsx_flow,
    list_fsx_directories_flow,
    list_fsx_files_flow,
    list_workspace_fsx_flow,
)
from app.repositories import mount_permissions as mount_perms_repo
from app.repositories import workspace_members as members_repo

logger = get_logger(__name__)

# 独立 router · 列候选池
fsx_router = APIRouter(tags=["fsx"])


class FsxFilesystemSummary(BaseModel):
    """候选池每项 (前端下拉用)."""

    filesystem_id: str
    name: str
    dns_name: str
    mount_name: str
    capacity_gib: int
    deployment_type: str | None = None
    subnet_id: str | None = None
    lifecycle: str = "AVAILABLE"


@fsx_router.get(
    "/fsx-filesystems",
    response_model=list[FsxFilesystemSummary],
    summary="列出候选 FSx 文件系统 · 仅超管",
    description=(
        "列 AWS 上打了 `managed=hyperpod` tag 的 FSx for Lustre 文件系统 (超管预建的候选池).\n\n"
        "**权限**: 仅平台超管. 前端超管配置页 / ws 建挂载表单前置数据源.\n\n"
        "**只读 AWS**, 不落库."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        502: {"description": "AWS FSx describe 失败"},
    },
)
async def list_fsx_filesystems_endpoint(
    current_user: dict[str, Any] = Depends(require_admin),
) -> list[FsxFilesystemSummary]:
    del current_user
    try:
        fs_list = await list_managed_filesystems()
    except FsxAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS FSx describe failed [{exc.code}]: {exc.message}",
        ) from exc
    return [FsxFilesystemSummary(**fs) for fs in fs_list]


class FsxDirectory(BaseModel):
    """FSx 盘根下的子目录, 创建工作空间时下拉用."""

    name: str = Field(description="目录名, 不含路径前缀")
    gid: int = Field(description="POSIX gid (group quota 维度)")


def _filter_dirs_by_primary_gid(
    dirs: list[dict[str, Any]], primary_gid: int | None
) -> list[dict[str, Any]]:
    """只保留 gid == primary_gid 的目录; primary_gid 为 None 返回空。"""
    if primary_gid is None:
        return []
    return [d for d in dirs if int(d.get("gid", -1)) == int(primary_gid)]


@fsx_router.get(
    "/fsx-filesystems/{filesystem_id}/directories",
    response_model=list[FsxDirectory],
    summary="列 FSx 盘内子目录 · 仅超管",
    description=(
        "列出该 FSx 盘 `<root>[/<path>]` 下的直接子目录, 每条带 POSIX `gid` "
        "(作为 group quota 维度). 盘根 = fsx-admin pod 内的 `/fsx-mnt/<filesystem_id>`.\n\n"
        "`path` 支持级联: 选定一层再传该层 path 列下一层. 非法路径 (含 `..`) 返 400.\n\n"
        "**降级返空**: `filesystem_id` 不在 `PLATFORM_FSX_FILESYSTEMS` 配置里、"
        "fsx-admin pod 不可用、exec 失败或目录为空, 都返 **空列表** (不报错, 前端退化为自由文本).\n\n"
        "**权限**: 仅平台超管. 训练任务代码目录选择器数据源.\n\n"
        "**只读 FSx**, 不落库."
    ),
    responses={
        400: {"description": "非法 path (含 `..` 等)"},
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
    },
)
async def list_fsx_directories_endpoint(
    filesystem_id: str,
    path: str = Query("", description="相对 /fsx 的子目录, 空=根; 级联列下一层用"),
    current_user: dict[str, Any] = Depends(require_admin),
) -> list[FsxDirectory]:
    """Return immediate subdirs under /fsx-mnt/<filesystem_id>[/<path>] with their gid.

    `path` 给训练任务代码目录级联选择用: 选定一层后传该层 path 列下一层.
    非法路径 (含 ..) 返 400; 其余失败 (未配盘 / 无 admin pod / exec 失败) 返空 list.
    """
    del current_user
    try:
        rows = await list_fsx_directories_flow(filesystem_id, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [FsxDirectory(**r) for r in rows]


class FsxFile(BaseModel):
    """FSx 盘内某目录下的普通文件, 训练任务选启动文件用."""

    name: str = Field(description="文件名, 不含路径前缀")


@fsx_router.get(
    "/fsx-filesystems/{filesystem_id}/files",
    response_model=list[FsxFile],
    summary="列 FSx 盘内普通文件 · 仅超管",
    description=(
        "列出该 FSx 盘 `<root>[/<path>]` 下的**普通文件** (跳目录 / 软链). "
        "盘根 = fsx-admin pod 内的 `/fsx-mnt/<filesystem_id>`. 训练任务启动文件下拉用.\n\n"
        "非法路径 (含 `..`) 返 400.\n\n"
        "**降级返空**: `filesystem_id` 未配置、fsx-admin pod 不可用、exec 失败或目录为空, "
        "都返 **空列表** (不报错).\n\n"
        "**权限**: 仅平台超管.\n\n"
        "**只读 FSx**, 不落库."
    ),
    responses={
        400: {"description": "非法 path (含 `..` 等)"},
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
    },
)
async def list_fsx_files_endpoint(
    filesystem_id: str,
    path: str = Query("", description="相对 /fsx 的子目录, 空=根; 列其下文件"),
    current_user: dict[str, Any] = Depends(require_admin),
) -> list[FsxFile]:
    """Return regular files under /fsx-mnt/<filesystem_id>[/<path>] (训练任务启动文件下拉用).

    非法路径 (含 ..) 返 400; 其余失败 (未配盘 / 无 admin pod / exec 失败) 返空 list.
    """
    del current_user
    try:
        rows = await list_fsx_files_flow(filesystem_id, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [FsxFile(**r) for r in rows]


# ===== Workspace 内 FSx 挂载 router (将挂在 workspace_router 下) =====

ws_fsx_router = APIRouter(tags=["fsx"])


class WorkspaceFsxMount(BaseModel):
    """ws 详情页 FSx tab 的一行."""

    mount_id: str = Field(default="", description="用户填的别名, ws 内 FSx 维度唯一")
    description: str = Field(default="", description="一句话说明 (≤200, 仅展示)")
    filesystem_id: str
    mount_path: str
    pv_name: str | None = None
    pvc_name: str | None = None  # 兼容旧字段 (= pvc_name_rw)
    pvc_name_rw: str | None = None
    pvc_name_ro: str | None = None
    attached_at: str
    # FSx 多租户隔离 (业务 Pod 创建时读)
    # 旧 mount 记录无此字段, 后端读 DDB 时给 None.
    subdir: str | None = None
    gid: int | None = None
    # FSx 元数据 (实时拉, 失败时 None)
    name: str | None = None
    capacity_gib: int | None = None
    dns_name: str | None = None
    # FSx 原始 lustre mountname + 拼 subdir (推理模型源 fsxStorage.mountName 锁 team 层用).
    mount_name: str | None = None
    full_mount_name: str | None = None


# mount_id 正则: 小写字母开头, 字母/数字/-, 3-40 字符
# (DNS-1123 label, K8s PVC/PV 名直接用)
_MOUNT_ID_PATTERN = r"^[a-z][a-z0-9-]{2,39}$"


class FsxAttachRequest(BaseModel):
    mount_id: str = Field(
        pattern=_MOUNT_ID_PATTERN,
        description="挂载 ID · 用户填的别名, ws 内 FSx 维度唯一. 例: imagenet",
    )
    description: str = Field(
        default="",
        max_length=200,
        description="一句话说明 (≤200, 支持中文, 仅展示)",
    )
    filesystem_id: str = Field(min_length=1)
    subdir: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_/-]+$",
        description="FSx /fsx/<subdir>, 支持多级子路径如 team-a/train/proj-b",
    )
    mount_path: str = Field(
        pattern=r"^/[a-zA-Z0-9_/-]+$",
        min_length=2,
        max_length=128,
        description="Pod 内挂载路径, 必须 / 开头",
    )


@ws_fsx_router.get(
    "/{ws_id}/fsx",
    response_model=list[WorkspaceFsxMount],
    summary="列出工作空间已挂 FSx",
    description=(
        "返回该 ws 下所有 FSx 挂载记录 (含 mount_id / subdir / gid / PV / PVC 名 / 实时 FSx 元数据).\n\n"
        "设计上每个 ws 通常挂**一个** FSx for Lustre 主盘. 多挂支持但少见.\n\n"
        "**权限**: 仅 ws 成员或平台超管 (越权修复 2026-06-14).\n\n"
        "**读 DDB + 实时补 FSx 元数据** (失败字段返 None), 不写库."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace 不存在"},
    },
)
async def list_workspace_fsx_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[WorkspaceFsxMount]:
    # 仅 ws 成员或平台超管可看挂载 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    rows = await list_workspace_fsx_flow(ws_id)
    return [WorkspaceFsxMount(**r) for r in rows]


@ws_fsx_router.post(
    "/{ws_id}/fsx",
    response_model=list[WorkspaceFsxMount],
    status_code=status.HTTP_201_CREATED,
    summary="挂载 FSx 到工作空间",
    description=(
        "把候选池中的一个 FSx 挂到本 ws:\n"
        "1. 后端 exec fsx-admin pod 探测 `subdir` 的真实 POSIX gid (子目录 gid 可能 ≠ 父目录)\n"
        "2. 在 ws namespace 下**恒双建** rw + ro 两套 PV + PVC (ro 靠 mountOptions `[ro]`, 不可选), "
        "指向该 FSx 的 `<mountName>/<subdir>`\n"
        "3. 回读校验两个 PVC 都真的存在, 再落 DDB `metadata_json.fsx_mounts`\n"
        "4. ws 首次成功挂载时把探测到的 gid 固化为 `metadata_json.primary_gid`; "
        "卸掉最后一个挂载时清空\n\n"
        "**gid 隔离规则**: 平台超管**完全豁免** (可首挂、可挂任意 gid). 非超管: "
        "ws 还没 `primary_gid` 时直接 403 \"首个 FSx 挂载需平台管理员操作\"; "
        "有 `primary_gid` 时探测 gid 必须相等, 否则 403.\n\n"
        "**非幂等**: 同 `mount_id` / 同 `(filesystem_id, subdir)` / 同 `mount_path` 重复挂都返 409."
        "\n\n**权限**: 仅 ws admin 或平台超管."
    ),
    responses={
        400: {"description": "gid 探测失败 (目录不存在 / fsx-admin 不可用), 或 FSx 非 Lustre / 非 AVAILABLE / describe 报错, 或 ws 无 namespace"},
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管; 或非超管首挂 / gid 与 primary_gid 不匹配"},
        404: {"description": "Workspace 不存在, 或 FSx 文件系统不存在"},
        409: {"description": "mount_id / (filesystem_id, subdir) / mount_path 已被占用"},
        422: {"description": "payload 校验失败"},
        500: {"description": "DDB 更新失败 (PV/PVC 已回滚)"},
        502: {"description": "K8s 建 PV/PVC 失败, 或 PVC 回读校验失败 (均已回滚)"},
    },
)
async def attach_fsx_endpoint(
    ws_id: str,
    payload: FsxAttachRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    k8s: K8sClient = Depends(get_k8s_client),
) -> list[WorkspaceFsxMount]:
    await assert_ws_admin(ws_id, current_user)
    rows = await attach_fsx_flow(
        ws_id=ws_id,
        filesystem_id=payload.filesystem_id,
        mount_path=payload.mount_path,
        subdir=payload.subdir,
        mount_id=payload.mount_id,
        description=payload.description,
        current_user=current_user,
        k8s=k8s,
    )
    return [WorkspaceFsxMount(**r) for r in rows]


@ws_fsx_router.delete(
    "/{ws_id}/fsx/{mount_id}",
    response_model=list[WorkspaceFsxMount],
    summary="卸载 FSx 挂载 · 仅超管",
    description=(
        "按 `mount_id` 卸载: 删 rw + ro 两套 PV / PVC (删 K8s 资源失败只 warn, 不中断) "
        "+ 清 DDB 记录 + 级联清该挂载的成员级 grants.\n\n"
        "**占用检查**: 默认扫 ws namespace 下是否还有 Pod 引用 rw / ro 任一 PVC, 有则返 409. "
        "`force=true` 跳过检查 (在挂链的 Pod 会立刻 IO 报错, 慎用).\n\n"
        "**权限**: 仅平台超管.\n\n"
        "**非幂等**: 已不在挂载表返 404. 返回卸载后剩余的挂载列表."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "Workspace 或挂载记录不存在"},
        409: {"description": "仍有 Pod 引用该 FSx (可用 force=true 强卸)"},
        502: {"description": "K8s API 失败"},
    },
)
async def detach_fsx_endpoint(
    ws_id: str,
    mount_id: str,
    force: bool = Query(default=False, description="Skip pod-occupancy check"),
    current_user: dict[str, Any] = Depends(require_admin),
    k8s: K8sClient = Depends(get_k8s_client),
) -> list[WorkspaceFsxMount]:
    rows = await detach_fsx_flow(
        ws_id=ws_id,
        mount_id=mount_id,
        force=force,
        current_user=current_user,
        k8s=k8s,
    )
    return [WorkspaceFsxMount(**r) for r in rows]


# ===== ws 级候选池 / 可挂目录 (挂载表单用, ws 管理员可见) =====


@ws_fsx_router.get(
    "/{ws_id}/fsx/candidate-filesystems",
    response_model=list[FsxFilesystemSummary],
    summary="列 ws 可挂 FSx 候选池 (ws admin 用)",
    description=(
        "ws admin 建挂载表单时用: 列 AWS 上打了 `managed=hyperpod` tag 的 FSx (与超管候选池同源, 但走 ws 级鉴权).\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**只读 AWS**, 不落库."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        502: {"description": "AWS FSx describe 失败"},
    },
)
async def list_ws_fsx_candidates_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[FsxFilesystemSummary]:
    await assert_ws_admin(ws_id, current_user)
    try:
        fs_list = await list_managed_filesystems()
    except FsxAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS FSx describe failed [{exc.code}]: {exc.message}",
        ) from exc
    return [FsxFilesystemSummary(**fs) for fs in fs_list]


@ws_fsx_router.get(
    "/{ws_id}/fsx/candidate-filesystems/{filesystem_id}/mountable-dirs",
    response_model=list[FsxDirectory],
    summary="列 ws 可挂 FSx 子目录 (gid 匹配)",
    description=(
        "ws admin 建挂载表单时用: 列指定 FSx 下 `gid == ws.primary_gid` 的子目录 (团队隔离硬约束).\n\n"
        "`path` 支持级联; 非法路径 (含 `..`) 返 400. ws 未配 `primary_gid` 时返空; "
        "`filesystem_id` 未配置 / fsx-admin pod 不可用时也返空 (不报错)."
        "\n\n**权限**: 仅 ws admin 或平台超管."
    ),
    responses={
        400: {"description": "非法 path (含 `..` 等)"},
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        404: {"description": "Workspace 不存在"},
    },
)
async def list_ws_mountable_dirs_endpoint(
    ws_id: str,
    filesystem_id: str,
    path: str = Query("", description="相对 /fsx 的子目录, 空=根"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[FsxDirectory]:
    await assert_ws_admin(ws_id, current_user)
    ws = await _get_ws_or_404(ws_id)
    primary_gid = (ws.get("metadata_json") or {}).get("primary_gid")
    try:
        rows = await list_fsx_directories_flow(filesystem_id, path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    filtered = _filter_dirs_by_primary_gid(
        rows, int(primary_gid) if primary_gid is not None else None
    )
    return [FsxDirectory(**r) for r in filtered]


# ===== 成员级授权 (grants) =====


class GrantRequest(BaseModel):
    username: str = Field(min_length=1, description="被授权的 ws 成员 username")
    access: str = Field(pattern=r"^(ro|rw)$", description="ro 只读 / rw 读写")


class GrantInfo(BaseModel):
    username: str
    access: str
    mount_id: str
    granted_by: str = ""
    granted_at: str = ""


def _find_mount_or_404(ws: dict[str, Any], mount_id: str) -> dict[str, Any]:
    mounts = (ws.get("metadata_json") or {}).get("fsx_mounts") or []
    for m in mounts:
        if m.get("mount_id") == mount_id:
            return m
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"FSx mount_id '{mount_id}' not found in workspace",
    )


def _to_grant_info(rows: list[dict[str, Any]], mount_id: str) -> list[GrantInfo]:
    return [
        GrantInfo(
            username=r.get("username", ""),
            access=r.get("access", ""),
            mount_id=r.get("mount_id", mount_id),
            granted_by=r.get("granted_by", ""),
            granted_at=r.get("granted_at", ""),
        )
        for r in rows
    ]


@ws_fsx_router.get(
    "/{ws_id}/fsx/{mount_id}/grants",
    response_model=list[GrantInfo],
    summary="列 FSx 挂载的成员授权",
    description=(
        "列出该 FSx 挂载下所有已授权成员及其 ro/rw 权限. "
        "不校验 ws / 挂载是否存在: 未知 `ws_id` 或 `mount_id` 直接返空列表.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**纯读 DDB**."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
    },
)
async def list_grants_endpoint(
    ws_id: str,
    mount_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[GrantInfo]:
    await assert_ws_admin(ws_id, current_user)
    rows = await mount_perms_repo.list_by_mount(ws_id, mount_id)
    return _to_grant_info(rows, mount_id)


@ws_fsx_router.post(
    "/{ws_id}/fsx/{mount_id}/grants",
    response_model=list[GrantInfo],
    status_code=status.HTTP_201_CREATED,
    summary="授权成员访问 FSx 挂载",
    description=(
        "给 ws 成员在该 FSx 挂载上开 ro/rw 权限. 授权信息 (username / access / mount_path / gid / PVC 名) 落 DDB, "
        "业务 Pod 创建时读它决定挂 rw-PVC 还是 ro-PVC.\n\n"
        "被授权用户必须已是本 ws 成员; 未加入返 404.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "幂等: 同 username 重发覆盖旧 access (记录 granter / granted_at 更新)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        404: {"description": "Workspace / 挂载 / 成员不存在"},
        422: {"description": "payload 校验失败 (access 非 ro/rw)"},
    },
)
async def create_grant_endpoint(
    ws_id: str,
    mount_id: str,
    payload: GrantRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[GrantInfo]:
    await assert_ws_admin(ws_id, current_user)
    ws = await _get_ws_or_404(ws_id)
    mount = _find_mount_or_404(ws, mount_id)
    # 校验 username 是该 ws 的成员
    member = await members_repo.get_member(ws_id, payload.username)
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{payload.username}' is not a member of workspace {ws_id}",
        )
    gid_raw = mount.get("gid")
    gid = int(gid_raw) if gid_raw is not None else 0
    granter = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    await mount_perms_repo.grant(
        workspace_id=ws_id,
        mount_id=mount_id,
        username=payload.username,
        access=payload.access,
        mount_path=mount.get("mount_path", ""),
        gid=gid,
        pvc_name_rw=mount.get("pvc_name_rw") or mount.get("pvc_name") or "",
        pvc_name_ro=mount.get("pvc_name_ro") or "",
        granted_by=granter,
    )
    rows = await mount_perms_repo.list_by_mount(ws_id, mount_id)
    return _to_grant_info(rows, mount_id)


@ws_fsx_router.delete(
    "/{ws_id}/fsx/{mount_id}/grants/{username}",
    response_model=list[GrantInfo],
    summary="撤销成员对 FSx 挂载的授权",
    description=(
        "撤销指定成员在该 FSx 挂载上的 ro/rw 权限. 已在跑的 Pod 不受影响, 新建的 Pod 拿不到该 PVC.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**幂等**: 不校验 ws / 挂载 / 授权是否存在, 未授权也正常返当前剩余授权列表, 不报错."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
    },
)
async def revoke_grant_endpoint(
    ws_id: str,
    mount_id: str,
    username: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[GrantInfo]:
    await assert_ws_admin(ws_id, current_user)
    await mount_perms_repo.revoke(ws_id, mount_id, username)
    rows = await mount_perms_repo.list_by_mount(ws_id, mount_id)
    return _to_grant_info(rows, mount_id)
