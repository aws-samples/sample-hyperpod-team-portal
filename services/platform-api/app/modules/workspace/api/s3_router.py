"""Workspace S3 挂载相关 HTTP 路由 (Mountpoint S3 CSI Driver).

GET    /api/v1/s3-buckets                            列候选池 (admin 预建打 managed=hyperpod)
GET    /api/v1/workspaces/{ws_id}/s3                  列已挂的 S3
POST   /api/v1/workspaces/{ws_id}/s3                  挂载 (建 PV+PVC)
DELETE /api/v1/workspaces/{ws_id}/s3/{mount_id}       卸载 (按 mount_id, force=true 跳过 pod 占用检查)

mount_id 在 ws 内 S3 维度唯一. 用户填别名, PV/PVC 名直接用.

S3 挂载全局只读: PV mountOptions 显式加 Mountpoint 原生 `read-only` flag
(仅"不加 allow-overwrite / allow-delete"还允许新建对象, 不够).
S3 仅用于读数据集/模型; 需写请走 boto3 SDK.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.adapters.aws.s3 import S3APIError, list_managed_buckets
from app.adapters.k8s import K8sClient
from app.core.logging import get_logger
from app.core.security import assert_ws_admin, assert_ws_member, get_current_user, require_admin
from app.modules.workspace.api.deps import get_k8s_client
from app.modules.workspace.orchestration.s3 import (
    attach_s3_flow,
    detach_s3_flow,
    list_workspace_s3_flow,
)

logger = get_logger(__name__)

# 候选池路由 (挂在 /api/v1/s3-buckets) · tag=s3-buckets 归入「S3 候选池」组
# (与 FSx 候选池独立成组对称; 别用 s3, 那是「S3 挂载」组)。
s3_bucket_router = APIRouter(tags=["s3-buckets"])


class S3BucketSummary(BaseModel):
    bucket_name: str
    name: str
    region: str


@s3_bucket_router.get(
    "/s3-buckets",
    response_model=list[S3BucketSummary],
    summary="列出候选 S3 桶 · 仅超管",
    description=(
        "列 AWS 上打了 `managed=hyperpod` tag 的 S3 桶 (超管预建的候选池).\n\n"
        "**权限**: 仅平台超管. 前端超管配置页 / ws 建挂载表单前置数据源.\n\n"
        "**只读 AWS**, 不落库."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        502: {"description": "AWS S3 list 失败"},
    },
)
async def list_managed_s3_buckets_endpoint(
    current_user: dict[str, Any] = Depends(require_admin),
) -> list[S3BucketSummary]:
    del current_user
    try:
        buckets = await list_managed_buckets()
    except S3APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS S3 list failed [{exc.code}]: {exc.message}",
        ) from exc
    return [
        S3BucketSummary(
            bucket_name=b["bucket_name"],
            name=b["name"],
            region=b["region"],
        )
        for b in buckets
    ]


# Workspace 内 S3 挂载路由 (挂在 workspace_router 下, /api/v1/workspaces/{id}/s3)
ws_s3_router = APIRouter(tags=["s3"])


class WorkspaceS3Mount(BaseModel):
    mount_id: str = Field(default="", description="用户填的别名, ws 内 S3 维度唯一")
    description: str = Field(default="", description="一句话说明 (≤200, 仅展示)")
    bucket_name: str
    prefix: str
    mount_path: str
    region: str
    pv_name: str
    pvc_name: str
    attached_at: str


# mount_id 正则: 跟 FSx 一致 (DNS-1123 label, 3-40 字符)
_MOUNT_ID_PATTERN = r"^[a-z][a-z0-9-]{2,39}$"


class S3AttachRequest(BaseModel):
    mount_id: str = Field(
        pattern=_MOUNT_ID_PATTERN,
        description="挂载 ID · 用户填的别名, ws 内 S3 维度唯一. 例: imagenet",
    )
    description: str = Field(
        default="",
        max_length=200,
        description="一句话说明 (≤200, 支持中文, 仅展示)",
    )
    bucket_name: str = Field(min_length=3, max_length=63)
    mount_path: str = Field(
        pattern=r"^/[a-zA-Z0-9_/-]+$",
        min_length=2,
        max_length=128,
        description="Pod 内挂载路径, / 开头",
    )
    prefix: str = Field(
        default="",
        max_length=512,
        description="bucket 内子路径前缀, 留空挂整个 bucket",
    )


@ws_s3_router.get(
    "/{ws_id}/s3/candidate-buckets",
    response_model=list[S3BucketSummary],
    summary="列 ws 可挂 S3 候选池 (ws admin 用)",
    description=(
        "ws admin 建挂载表单时用: 列 AWS 上打了 `managed=hyperpod` tag 的 S3 桶 (与超管候选池同源, 但走 ws 级鉴权).\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**只读 AWS**, 不落库."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        502: {"description": "AWS S3 list 失败"},
    },
)
async def list_ws_s3_candidates_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[S3BucketSummary]:
    await assert_ws_admin(ws_id, current_user)
    try:
        buckets = await list_managed_buckets()
    except S3APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS S3 list failed [{exc.code}]: {exc.message}",
        ) from exc
    return [
        S3BucketSummary(bucket_name=b["bucket_name"], name=b["name"], region=b["region"])
        for b in buckets
    ]


@ws_s3_router.get(
    "/{ws_id}/s3",
    response_model=list[WorkspaceS3Mount],
    summary="列出工作空间已挂 S3",
    description=(
        "返回该 ws 下所有 S3 挂载记录 (Mountpoint S3 CSI Driver).\n\n"
        "**权限**: 仅 ws 成员或平台超管 (越权修复 2026-06-14).\n\n"
        "**纯读 DDB**, 不请求 AWS."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Workspace 不存在"},
    },
)
async def list_workspace_s3_endpoint(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[WorkspaceS3Mount]:
    # 仅 ws 成员或平台超管可看挂载 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    rows = await list_workspace_s3_flow(ws_id)
    return [WorkspaceS3Mount(**r) for r in rows]


@ws_s3_router.post(
    "/{ws_id}/s3",
    response_model=list[WorkspaceS3Mount],
    status_code=status.HTTP_201_CREATED,
    summary="挂载 S3 桶到工作空间",
    description=(
        "把候选池中的一个 S3 桶挂到本 ws (Mountpoint S3 CSI):\n"
        "1. 校验桶存在并拿到 region (AWS HeadBucket)\n"
        "2. 在 ws namespace 下建 PV + PVC, 指向 `s3://<bucket>[/<prefix>]`\n"
        "3. 只读: PV mountOptions 显式带 Mountpoint 原生 `read-only` flag (拒绝新建/覆盖/删除)\n"
        "4. 落 DDB `metadata_json.s3_mounts`\n\n"
        "**只读**: S3 挂载仅用于读数据集/模型; 需写请走 boto3 SDK.\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**非幂等**: 同 `mount_id` 或同 `mount_path` (跨 FSx + S3 合并判重) 已占返 409. "
        "`(bucket, prefix)` **不再判重** — 可用不同 mount_id 挂同桶同前缀."
    ),
    responses={
        400: {"description": "桶不合法 / HeadBucket 报错 (非 NotFound), 或 ws 无 namespace"},
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        404: {"description": "Workspace 不存在, 或桶不存在"},
        409: {"description": "mount_id 或 mount_path 已被占用"},
        422: {"description": "payload 校验失败"},
        500: {"description": "DDB 更新失败 (PV/PVC 已回滚)"},
        502: {"description": "K8s 建 PV/PVC 失败 (已回滚)"},
    },
)
async def attach_s3_endpoint(
    ws_id: str,
    payload: S3AttachRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    k8s: K8sClient = Depends(get_k8s_client),
) -> list[WorkspaceS3Mount]:
    await assert_ws_admin(ws_id, current_user)
    rows = await attach_s3_flow(
        ws_id=ws_id,
        bucket_name=payload.bucket_name,
        mount_path=payload.mount_path,
        prefix=payload.prefix,
        mount_id=payload.mount_id,
        description=payload.description,
        current_user=current_user,
        k8s=k8s,
    )
    return [WorkspaceS3Mount(**r) for r in rows]


@ws_s3_router.delete(
    "/{ws_id}/s3/{mount_id}",
    response_model=list[WorkspaceS3Mount],
    summary="卸载 S3 挂载",
    description=(
        "按 `mount_id` 卸载 S3: 删 PV / PVC (删 K8s 资源失败只 warn, 不中断) + 清 DDB 记录.\n\n"
        "**占用检查**: 默认扫 ws namespace 下是否还有 Pod 引用该 PVC, 有则返 409. "
        "`force=true` 跳过检查 (在挂链的 Pod 会立刻 IO 报错, 慎用).\n\n"
        "**权限**: 仅 ws admin 或平台超管.\n\n"
        "**非幂等**: 已不在挂载表返 404. 返回卸载后剩余的挂载列表."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws admin 或超管"},
        404: {"description": "Workspace 或挂载记录不存在"},
        409: {"description": "仍有 Pod 引用该挂载 (可用 force=true 强卸)"},
        502: {"description": "K8s API 失败"},
    },
)
async def detach_s3_endpoint(
    ws_id: str,
    mount_id: str,
    force: bool = Query(default=False, description="Skip pod-occupancy check"),
    current_user: dict[str, Any] = Depends(get_current_user),
    k8s: K8sClient = Depends(get_k8s_client),
) -> list[WorkspaceS3Mount]:
    await assert_ws_admin(ws_id, current_user)
    rows = await detach_s3_flow(
        ws_id=ws_id,
        mount_id=mount_id,
        force=force,
        current_user=current_user,
        k8s=k8s,
    )
    return [WorkspaceS3Mount(**r) for r in rows]
