"""Dynamo 生命周期 (最小切片)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables as _tables
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.dynamo.domain.cr import otel_configmap_name
from app.modules.dynamo.persistence import crud
from app.repositories import resource_index as ri_repo
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)


async def _get_or_404(db: Any, id_: Any) -> dict[str, Any]:
    del db
    row = await crud.get(None, id_)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dynamo not found: {id_}")
    return row


async def _assert_can_operate(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    """delete/stop 操作权限: creator 本人 OR ws 管理员 OR 平台超管 (同 inference)。"""
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
        t("dynamo.forbidden_operate"),
    )


async def delete_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> None:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    try:
        await k8s.delete_dynamo_deployment(row["k8s_namespace"], row["k8s_cr_name"])
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s delete DynamoGraphDeployment failed: {exc.message}",
        ) from exc
    # 删 OTel configmap (随 CR 生命周期; 404 幂等, 失败不阻断)
    try:
        await k8s.delete_config_map(
            row["k8s_namespace"], otel_configmap_name(row["k8s_cr_name"])
        )
    except K8sAPIError:
        pass
    await ri_repo.mark_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_DYNAMO, row["id"]
    )
    await audit_dynamo(row, user, "dynamo.delete")
    logger.info("dynamo.delete.ok", id=str(id_), k8s_cr=row["k8s_cr_name"])


async def stop_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """停止: 删 CR (grove 级联回收 pod), DDB 行保留 phase=Stopped (同 inference)。"""
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    row = await crud.mark_stopped(None, row)
    try:
        await k8s.delete_dynamo_deployment(row["k8s_namespace"], row["k8s_cr_name"])
    except K8sAPIError as exc:
        if "404" not in exc.code:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"k8s delete DynamoGraphDeployment failed: {exc.message}",
            ) from exc
    # 停止也删 OTel configmap (CR 没了 sidecar 也没了, configmap 无用; 重建走 create 重建)
    try:
        await k8s.delete_config_map(
            row["k8s_namespace"], otel_configmap_name(row["k8s_cr_name"])
        )
    except K8sAPIError:
        pass
    await audit_dynamo(row, user, "dynamo.stop")
    logger.info("dynamo.stop.ok", id=str(id_), k8s_cr=row["k8s_cr_name"])
    return row


async def audit_dynamo(
    row: dict[str, Any],
    user: dict[str, Any] | None,
    operation: str,
    *,
    status_: str = "succeeded",
) -> None:
    """写一条操作审计 (append-only, 失败不阻塞; 照 inference audit)。"""
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
            target_type="dynamo",
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
            "dynamo.audit_fail", op=operation, id=str(row.get("id") or ""), err=str(exc)
        )
