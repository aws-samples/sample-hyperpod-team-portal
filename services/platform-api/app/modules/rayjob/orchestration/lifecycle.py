"""RayJob 生命周期 · 照 dynamo lifecycle。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables as _tables
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.rayjob.persistence import crud
from app.repositories import resource_index as ri_repo
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)


async def _get_or_404(db: Any, id_: Any) -> dict[str, Any]:
    del db
    row = await crud.get(None, id_)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id_}")
    return row


async def _assert_can_operate(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    """delete/stop 权限: creator 本人 OR ws 管理员 OR 平台超管 (同 dynamo)。"""
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
        t("rayjob.forbidden_operate"),
    )


async def delete_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> None:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    try:
        await k8s.delete_rayjob(row["k8s_namespace"], row["k8s_cr_name"])
    except K8sAPIError as exc:
        # 404 幂等: RayJob SUCCEEDED 后 shutdownAfterJobFinishes 已拆 CR, 删不到很正常,
        # 照删 DDB 行 (否则任务跑完就删不掉, 列表永远残留)。非 404 才真失败。
        if "404" not in exc.code:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"k8s delete RayJob failed: {exc.message}",
            ) from exc
    await ri_repo.mark_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_RAYJOB, row["id"]
    )
    await audit_rayjob(row, user, "rayjob.delete")
    logger.info("rayjob.delete.ok", id=str(id_), k8s_cr=row["k8s_cr_name"])


async def stop_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """停止: 删 RayJob CR (KubeRay 级联回收 RayCluster+pod), DDB 行保留 phase=Stopped。"""
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    row = await crud.mark_stopped(None, row)
    try:
        await k8s.delete_rayjob(row["k8s_namespace"], row["k8s_cr_name"])
    except K8sAPIError as exc:
        if "404" not in exc.code:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"k8s delete RayJob failed: {exc.message}",
            ) from exc
    await audit_rayjob(row, user, "rayjob.stop")
    logger.info("rayjob.stop.ok", id=str(id_), k8s_cr=row["k8s_cr_name"])
    return row


async def audit_rayjob(
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
            target_type="rayjob",
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
            "rayjob.audit_fail", op=operation, id=str(row.get("id") or ""), err=str(exc)
        )
