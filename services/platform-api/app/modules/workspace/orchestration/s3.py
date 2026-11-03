"""Workspace S3 挂载 / 卸载 orchestration.

跟 FSx 高度对称, 但有两点不同:
    - S3 用 (bucket, prefix) 复合标识 (一 ws 可挂同 bucket 不同 prefix)
    - 不需要预拉 DNS+MountName, 只要 bucket name + region

attach_s3_flow:
    1. 校验 ws 存在
    2. 校验 (bucket, prefix) 在该 ws 内唯一 (DDB metadata.s3_mounts)
    3. 校验 mount_path 不与已挂载冲突 (含 fsx_mounts)
    4. 校验 bucket 存在 (走 AWS HeadBucket)
    5. 建 K8s PV (claimRef 锁 ns/pvc, mountOptions 配 prefix)
    6. 建 K8s PVC (volumeName 双向绑)
    7. 改 DDB metadata.s3_mounts append 一项
    8. AuditLog

detach_s3_flow:
    1. 校验 ws 存在 + (bucket, prefix) 在挂载列表
    2. (force=False) 检查 pod 占用 → 占用则 409
    3. 删 PVC + 删 PV
    4. 改 DDB metadata.s3_mounts 移除该项
    5. AuditLog
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import s3 as s3_adapter
from app.adapters.aws.s3 import S3APIError
from app.adapters.ddb import tables as ddb_tables
from app.adapters.k8s import K8sAPIError, K8sClient
from app.adapters.k8s.workspace_resources import s3_pv_name as s3_pv_name_of
from app.adapters.k8s.workspace_resources import s3_pvc_name as s3_pvc_name_of
from app.core.logging import get_logger
from app.modules.workspace.persistence import crud
from app.repositories import audit_log as audit_repo
from app.repositories import workspaces as ws_repo

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _get_ws_or_404(ws_id: str) -> dict[str, Any]:
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workspace not found: {ws_id}",
        )
    return ws


def _all_existing_mount_paths(metadata: dict[str, Any]) -> set[str]:
    """所有已挂的 mount_path (FSx + S3 合并去重)."""
    out: set[str] = set()
    for m in metadata.get("fsx_mounts") or []:
        if m.get("mount_path"):
            out.add(m["mount_path"])
    for m in metadata.get("s3_mounts") or []:
        if m.get("mount_path"):
            out.add(m["mount_path"])
    return out


async def list_workspace_s3_flow(ws_id: str) -> list[dict[str, Any]]:
    """列已挂 S3 (从 DDB 读, 不调 AWS — bucket 元数据不会动态变)."""
    ws = await _get_ws_or_404(ws_id)
    metadata = ws.get("metadata_json") or {}
    mounts = list(metadata.get("s3_mounts") or [])
    return [
        {
            "mount_id": m.get("mount_id") or "",
            "description": m.get("description") or "",
            "bucket_name": m.get("bucket_name") or "",
            "prefix": m.get("prefix") or "",
            "mount_path": m.get("mount_path") or "",
            "region": m.get("region") or "",
            "pv_name": m.get("pv_name") or "",
            "pvc_name": m.get("pvc_name") or "",
            "attached_at": m.get("attached_at") or "",
        }
        for m in mounts
    ]


async def attach_s3_flow(
    *,
    ws_id: str,
    bucket_name: str,
    mount_path: str,
    prefix: str,
    mount_id: str,
    description: str,
    current_user: dict[str, Any],
    k8s: K8sClient,
) -> list[dict[str, Any]]:
    """挂载 S3 bucket (可选 prefix) 到 ws.

    mount_id: 用户填的别名, S3 维度 ws 内唯一. PV/PVC 名 = pv-ws-{ws_id}-s3-{mount_id} /
              pvc-ws-s3-{mount_id}.
    description: 一句话备注 (≤200), 仅展示用.
    (bucket, prefix) 在 ws 内不再做重复校验, 用户可以用不同 mount_id 挂同 bucket 同 prefix.
    """
    ws = await _get_ws_or_404(ws_id)
    metadata = ws.get("metadata_json") or {}
    namespace = metadata.get("namespace") or ws.get("namespace")
    workspace_name = metadata.get("name") or ws.get("display_name") or ""

    if not namespace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace has no namespace (data inconsistency)",
        )

    existing: list[dict[str, Any]] = list(metadata.get("s3_mounts") or [])

    # mount_id 在 S3 维度 ws 内唯一
    for m in existing:
        if m.get("mount_id") == mount_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"S3 mount_id '{mount_id}' already exists in workspace",
            )

    # 校验 mount_path 不与任何已挂 (含 FSx) 冲突
    used_paths = _all_existing_mount_paths(metadata)
    if mount_path in used_paths:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"mount_path {mount_path} already used (FSx or S3)",
        )

    # 校验 bucket 存在 + 拿 region
    try:
        bucket_info = await s3_adapter.verify_bucket(bucket_name)
    except S3APIError as exc:
        if exc.code == "NotFound":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    region = bucket_info["region"]

    # 建 PV + PVC
    pv_full_name: str | None = None
    pvc_full_name: str | None = None
    try:
        pv_full_name = await k8s.create_s3_pv(
            workspace_id=str(ws_id),
            workspace_name=workspace_name,
            namespace=namespace,
            bucket_name=bucket_name,
            region=region,
            prefix=prefix,
            mount_id=mount_id,
        )
        pvc_full_name = await k8s.create_s3_pvc(
            namespace=namespace,
            workspace_name=workspace_name,
            bucket_name=bucket_name,
            pv_full_name=pv_full_name,
            mount_id=mount_id,
        )
    except K8sAPIError as exc:
        if pvc_full_name:
            try:
                await k8s.delete_pvc(namespace, pvc_full_name)
            except Exception:
                pass
        if pv_full_name:
            try:
                await k8s.delete_pv(pv_full_name)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"K8s create S3 PV/PVC failed [{exc.code}]: {exc.message}",
        ) from exc

    # 改 DDB metadata.s3_mounts (mount_id 主键)
    new_mount = {
        "mount_id": mount_id,
        "description": description,
        "bucket_name": bucket_name,
        "prefix": prefix,
        "mount_path": mount_path,
        "region": region,
        "pv_name": pv_full_name,
        "pvc_name": pvc_full_name,
        "attached_at": _now_iso(),
    }
    new_mounts = existing + [new_mount]
    new_metadata = dict(metadata)
    new_metadata["s3_mounts"] = new_mounts
    try:
        await ws_repo.update_workspace(ws_id, metadata=new_metadata)
    except Exception as exc:
        try:
            await k8s.delete_pvc(namespace, pvc_full_name)
        except Exception:
            pass
        try:
            await k8s.delete_pv(pv_full_name)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DDB update failed (K8s rolled back): {exc}",
        ) from exc

    # AuditLog
    actor = current_user
    actor_username = str(actor.get("username") or actor.get("user_id") or "")
    try:
        await audit_repo.append(
            scope_key=ddb_tables.scope_key_workspace(str(ws_id)),
            actor_user_id=actor_username,
            actor_role="platform-admin",
            operation="workspace.s3.attach",
            target_type="workspace",
            target_id=str(ws_id),
            status="succeeded",
            metadata={
                "mount_id": mount_id,
                "bucket_name": bucket_name,
                "prefix": prefix,
                "mount_path": mount_path,
                "region": region,
                "pv_name": pv_full_name,
                "pvc_name": pvc_full_name,
                "actor_email": actor.get("email") or "",
            },
        )
    except Exception as audit_exc:  # pragma: no cover
        logger.warning(
            "workspace.s3.attach.audit_fail", ws_id=ws_id, err=str(audit_exc)
        )

    logger.info(
        "workspace.s3.attach.ok",
        ws_id=ws_id,
        mount_id=mount_id,
        bucket=bucket_name,
        prefix=prefix or "(root)",
        mount_path=mount_path,
    )
    return await list_workspace_s3_flow(ws_id)


async def detach_s3_flow(
    *,
    ws_id: str,
    mount_id: str,
    force: bool,
    current_user: dict[str, Any],
    k8s: K8sClient,
) -> list[dict[str, Any]]:
    """卸载 S3 挂载 (按 mount_id)."""
    ws = await _get_ws_or_404(ws_id)
    metadata = ws.get("metadata_json") or {}
    namespace = metadata.get("namespace") or ws.get("namespace")
    existing: list[dict[str, Any]] = list(metadata.get("s3_mounts") or [])

    target = None
    target_idx = -1
    for i, m in enumerate(existing):
        if m.get("mount_id") == mount_id:
            target = m
            target_idx = i
            break
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"S3 mount_id '{mount_id}' not attached to workspace {ws_id}",
        )

    bucket_name = target.get("bucket_name") or ""
    prefix = target.get("prefix") or ""
    # 优先用 DDB 字面值 (新规则下 mount_id 一定有, 这里 fallback 防万一)
    pv_full_name = target.get("pv_name") or s3_pv_name_of(str(ws_id), mount_id)
    pvc_full_name = target.get("pvc_name") or s3_pvc_name_of(mount_id)

    # force=False 时检查 pod 占用
    if not force and namespace:
        try:
            pods = await k8s.list_pods_using_pvc(namespace, pvc_full_name)
        except K8sAPIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"K8s list pods failed [{exc.code}]: {exc.message}",
            ) from exc
        if pods:
            pod_names = [(p.get("metadata") or {}).get("name") for p in pods]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{len(pods)} pod(s) still using S3 mount '{mount_id}': "
                    f"{', '.join(filter(None, pod_names))}. "
                    "Use ?force=true to detach anyway."
                ),
            )

    # 删 PVC + PV
    if namespace:
        try:
            await k8s.delete_pvc(namespace, pvc_full_name)
        except K8sAPIError as exc:
            logger.warning(
                "workspace.s3.detach.pvc_fail",
                ws_id=ws_id, pvc=pvc_full_name, err=str(exc),
            )
    try:
        await k8s.delete_pv(pv_full_name)
    except K8sAPIError as exc:
        logger.warning(
            "workspace.s3.detach.pv_fail",
            ws_id=ws_id, pv=pv_full_name, err=str(exc),
        )

    # 改 DDB (按 idx 删, 防多 prefix 误删)
    new_mounts = [m for i, m in enumerate(existing) if i != target_idx]
    new_metadata = dict(metadata)
    new_metadata["s3_mounts"] = new_mounts
    await ws_repo.update_workspace(ws_id, metadata=new_metadata)

    # AuditLog
    actor = current_user
    actor_username = str(actor.get("username") or actor.get("user_id") or "")
    try:
        await audit_repo.append(
            scope_key=ddb_tables.scope_key_workspace(str(ws_id)),
            actor_user_id=actor_username,
            actor_role="platform-admin",
            operation="workspace.s3.detach",
            target_type="workspace",
            target_id=str(ws_id),
            status="succeeded",
            metadata={
                "mount_id": mount_id,
                "bucket_name": bucket_name,
                "prefix": prefix,
                "pv_name": pv_full_name,
                "pvc_name": pvc_full_name,
                "force": force,
                "actor_email": actor.get("email") or "",
            },
        )
    except Exception as audit_exc:  # pragma: no cover
        logger.warning(
            "workspace.s3.detach.audit_fail", ws_id=ws_id, err=str(audit_exc)
        )

    logger.info(
        "workspace.s3.detach.ok",
        ws_id=ws_id, mount_id=mount_id, bucket=bucket_name,
        prefix=prefix or "(root)", force=force,
    )
    return await list_workspace_s3_flow(ws_id)
