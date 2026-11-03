"""llm-d 生命周期 (最小切片 分支B).

与 dynamo 差异: 删的是一组资源 (delete_llmd_resources 按 name 前缀级联), 非单 CR。
delete 用 base name (= row["name"]), adapter 内部拼 <name>-multi / <name>-gateway / <name>-otel。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables as _tables
from app.adapters.k8s.workspace_resources import s3_pv_name, s3_pvc_name
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.llmd.persistence import crud
from app.repositories import resource_index as ri_repo
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)


async def _cleanup_s3_pv_pvc(k8s: K8sClient, row: dict[str, Any]) -> None:
    """删自建的 S3 PV/PVC (mount_id = llmd name, 与 create 一致); 404 幂等, 失败只 warning。"""
    if row.get("model_source_type") != "s3":
        return
    ws_id = str(row.get("workspace_id") or "")
    name = row.get("name") or ""
    ns = row.get("k8s_namespace") or ""
    try:
        await k8s.delete_pvc(ns, s3_pvc_name(name))
    except K8sAPIError as exc:
        logger.warning("llmd.s3_pvc.cleanup_fail", name=name, err=str(exc))
    try:
        await k8s.delete_pv(s3_pv_name(ws_id, name))
    except K8sAPIError as exc:
        logger.warning("llmd.s3_pv.cleanup_fail", name=name, err=str(exc))


async def _get_or_404(db: Any, id_: Any) -> dict[str, Any]:
    del db
    row = await crud.get(None, id_)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"llmd not found: {id_}")
    return row


async def _assert_can_operate(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    """delete/stop 操作权限: creator 本人 OR ws 管理员 OR 平台超管 (同 dynamo)。"""
    if user is None:
        return
    username = str(user.get("user_id") or user.get("username") or user.get("id") or "")
    if username and username == str(row.get("creator_user_id") or ""):
        return
    from app.core.security import is_ws_admin
    if await is_ws_admin(str(row.get("workspace_id") or ""), user):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        t("llmd.forbidden_operate"),
    )


async def delete_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> None:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    # 级联删一组资源 (adapter 内单个 404 幂等, 尽力删完)
    try:
        await k8s.delete_llmd_resources(row["k8s_namespace"], row["name"])
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s delete llmd resources failed: {exc.message}",
        ) from exc
    # s3 源: 清自建的 PV/PVC (fsx 不动, PVC 是 ws 共享的)
    await _cleanup_s3_pv_pvc(k8s, row)
    await ri_repo.mark_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_LLMD, row["id"]
    )
    await audit_llmd(row, user, "llmd.delete")
    logger.info("llmd.delete.ok", id=str(id_), name=row["name"])


async def stop_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """停止: 删资源组 (LWS 级联回收 pod), DDB 行保留 phase=Stopped (同 dynamo)。"""
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    row = await crud.mark_stopped(None, row)
    # delete_llmd_resources 内部单个 404 幂等, 尽力删完
    try:
        await k8s.delete_llmd_resources(row["k8s_namespace"], row["name"])
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s delete llmd resources failed: {exc.message}",
        ) from exc
    # s3 源: 清自建的 PV/PVC (释算力时一并清; 克隆重建会按新 name 重新建)
    await _cleanup_s3_pv_pvc(k8s, row)
    await audit_llmd(row, user, "llmd.stop")
    logger.info("llmd.stop.ok", id=str(id_), name=row["name"])
    return row


async def audit_llmd(
    row: dict[str, Any],
    user: dict[str, Any] | None,
    operation: str,
    *,
    status_: str = "succeeded",
) -> None:
    """写一条操作审计 (append-only, 失败不阻塞; 照 dynamo audit)。"""
    from app.repositories import audit_log as audit_repo

    actor = user or {}
    actor_username = str(
        actor.get("username") or actor.get("user_id") or actor.get("id") or ""
    )
    try:
        await audit_repo.append(
            scope_key=_tables.scope_key_workspace(str(row.get("workspace_id") or "")),
            actor_user_id=actor_username,
            actor_role="platform-admin" if actor.get("is_admin") else "member",
            operation=operation,
            target_type="llmd",
            target_id=str(row.get("id") or ""),
            status=status_,
            metadata={
                "display_name": row.get("display_name") or "",
                "creator": row.get("creator_user_id") or "",
                "actor_email": actor.get("email") or "",
                "actor_display_name": actor.get("display_name") or "",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "llmd.audit_fail", op=operation, id=str(row.get("id") or ""), err=str(exc)
        )
