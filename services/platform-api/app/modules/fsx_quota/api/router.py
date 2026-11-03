"""FSx 目录配额 HTTP 路由 (平台超管 only)。

监控指标 (CloudWatch) 已拆到 monitoring_router (所有登录用户可看)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.core.logging import get_logger
from app.core.security import require_admin
from app.modules.fsx_quota.api.schemas import (
    CreateDirPayload,
    DirQuota,
    DirQuotaList,
    UpdateQuotaPayload,
)
from app.modules.fsx_quota.orchestration.quota import (
    FsxQuotaError,
    create_directory,
    list_directories,
    update_quota,
)

logger = get_logger(__name__)

fsx_quota_router = APIRouter(
    prefix="/admin/fsx-quota",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@fsx_quota_router.get(
    "/directories",
    response_model=DirQuotaList,
    summary="列 FSx 一级目录用量 + 配额 · 仅超管",
    description=(
        "读取指定 FSx (`filesystem_id`, 须在 `PLATFORM_FSX_FILESYSTEMS` 配了) 下"
        "**所有一级目录**的 lfs project quota 记录 "
        "(gid / pid / 已用 / soft / hard / 使用率) 并附 FS 总容量.\n\n"
        "**数据源**: 一次 fsx-admin pod exec 拉全部目录的 `lfs project` + `lfs quota` "
        "并行输出解析 (避免逐目录多次 exec, 单趟 ~3.6s). **FS 是唯一 source of truth**, 不落库.\n\n"
        "**权限**: 仅平台超管. 前端管理中心 / FSx 配额页数据源."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        502: {
            "description": "fsx-admin pod exec 失败 (lustre-client 未装 / Pod 未就绪), "
            "或 `filesystem_id` 未在 `PLATFORM_FSX_FILESYSTEMS` 配置 "
            "(所有 FsxQuotaError 统一映射 502)"
        },
    },
)
async def get_directories(
    filesystem_id: str = Query(..., description="FSx 文件系统 id (fs-xxxx)"),
) -> dict[str, Any]:
    try:
        return await list_directories(filesystem_id)
    except FsxQuotaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@fsx_quota_router.post(
    "/directories",
    response_model=DirQuota,
    summary="建一级目录 + 分配 project quota · 仅超管",
    description=(
        "在 fsx-admin pod 的挂载根 `/fsx-mnt/<filesystem_id>/` 下建一个 team 一级目录"
        "并落地 project quota. 一趟 shell (`&&` 串联) 内做:\n"
        "1. `mkdir <root>/<name>` + `chown :<gid>` (**只改组, owner 不动**) + "
        "`chmod 2770` (setgid, 保子目录 gid 继承)\n"
        "2. `lfs project -p <pid> -r -s <root>/<name>` 打 project tag\n"
        "3. `lfs setquota -p <pid> -b <soft>G -B <hard>G <root>` (soft = hard × 80%)\n"
        "4. 回读校验 (回读 hard 小于请求值即判失败)\n\n"
        "**gid 分配**: `gid` 传 = 复用已有 team (跨目录共享 gid, 传未知 gid 会被拒); "
        "不传 = 后端自动新分配. **pid 永远独立** — 每目录一个新 pid, 便于按目录独立限额.\n\n"
        "**容量约束**: 各目录 hard 之和 ≤ FS 总容量 (拿不到总容量时跳过校验放行).\n\n"
        "**权限**: 仅平台超管."
    ),
    responses={
        400: {"description": "name 非法 (只允许字母/数字/`. _ -`, 单层, 拒 `..`)"},
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        502: {
            "description": "**同名目录已存在** / gid 不属于任何已有目录 / hard 之和超 FS 总容量 "
            "/ 回读校验失败 / fsx-admin pod exec 失败 / filesystem_id 未配置 "
            "(FsxQuotaError 全部映射 502, 不返 409)"
        },
    },
)
async def post_directory(payload: CreateDirPayload) -> dict[str, Any]:
    try:
        return await create_directory(
            payload.filesystem_id, payload.name, payload.hard_gib, payload.gid
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except FsxQuotaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@fsx_quota_router.patch(
    "/directories/{name}",
    response_model=DirQuota,
    summary="改一级目录 project quota · 仅超管",
    description=(
        "调整已有一级目录的硬配额 (soft 自动跟随 = hard × 80%).\n\n"
        "**兼容旧目录**: 目标目录若 `pid == 0` (未纳管的历史目录), 会**顺带纳管** — "
        "递归打 project tag + setquota, 之后即可正常出现在列表用量里.\n\n"
        "**容量约束**: 排除本目录旧值后, 其余目录 hard 之和 + 新值 ≤ FS 总容量.\n\n"
        "**权限**: 仅平台超管."
    ),
    responses={
        400: {"description": "目录名非法 (只允许字母/数字/`. _ -`, 单层, 拒 `..`)"},
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        502: {
            "description": "**目录不存在** / hard 之和超 FS 总容量 / 回读校验失败 / "
            "fsx-admin pod exec 失败 / filesystem_id 未配置 "
            "(FsxQuotaError 全部映射 502)"
        },
    },
)
async def patch_directory(
    payload: UpdateQuotaPayload, name: str = Path(...)
) -> dict[str, Any]:
    try:
        return await update_quota(payload.filesystem_id, name, payload.hard_gib)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except FsxQuotaError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
