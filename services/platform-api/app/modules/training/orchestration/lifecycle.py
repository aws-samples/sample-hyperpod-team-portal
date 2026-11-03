"""Training job 生命周期 (DDB-only)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables as _tables
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.training.persistence import crud
from app.repositories import resource_index as ri_repo
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)


async def _get_or_404(db: Any, id_: Any) -> dict[str, Any]:
    del db
    row = await crud.get(None, id_)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id_}"
        )
    return row


async def _assert_can_operate(
    row: dict[str, Any], user: dict[str, Any] | None
) -> None:
    """训练任务 delete 的操作权限闸:
    creator 本人 OR ws 管理员 OR 平台超管 才放行, 否则 403。
    user=None 时跳过 (informer/worker 内部调用, 无用户上下文)。
    """
    if user is None:
        return
    username = str(
        user.get("user_id") or user.get("username") or user.get("id") or ""
    )
    if username and username == str(row.get("creator_user_id") or ""):
        return
    from app.core.security import is_ws_admin
    if await is_ws_admin(str(row.get("workspace_id") or ""), user):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        t("training.forbidden_operate"),
    )


async def delete_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> None:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    try:
        await k8s.delete_hyperpod_pytorch_job(
            row["k8s_namespace"], row["k8s_job_name"]
        )
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s delete HyperPodPyTorchJob failed: {exc.message}",
        ) from exc
    # 软删 DDB 行 (打 deleted_at), 不硬删 — 列表页过滤掉, 审计仍可查。
    # informer 收到 K8s DELETED 事件后会再 mark_deleted 一次 (幂等), 此处自己先
    # 打标避免 worker 未运行时产生孤儿行 (CR 已删但 DDB 行无 deleted_at 永久残留)。
    await ri_repo.mark_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_TRAIN, row["id"]
    )
    # 级联清分享记录 (best-effort, 失败不阻塞删除)。
    try:
        from app.repositories import resource_shares as shares_repo
        await shares_repo.delete_by_resource(
            row["workspace_id"], _tables.RESOURCE_TYPE_TRAIN, row["id"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "training.delete.share_cleanup_fail",
            id=str(id_), err=str(exc),
        )
    await audit_training(row, user, "training.delete")
    logger.info(
        "training.delete.ok", id=str(id_), k8s_cr=row["k8s_job_name"]
    )


async def stop_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    """停止训练: 删 K8s Job (operator 级联 Pod, 释放 GPU), DDB 行保留 phase=Stopped。
    非暂停恢复 — 训练无 resume; 留记录/配置供查日志 + 克隆重跑。区别于 delete_flow (软删)。
    """
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    # 顺序: 先 mark_stopped (phase=Stopped + stop_requested) 再删 CR。
    # 否则删 CR 后 informer 收 DELETED 时 row 还是运行态, stop_requested 哨兵未置 → 被软删。
    row = await crud.mark_stopped(None, row)
    try:
        await k8s.delete_hyperpod_pytorch_job(
            row["k8s_namespace"], row["k8s_job_name"]
        )
    except K8sAPIError as exc:
        # 404 = CR 已不在 (重复停止 / 已被删), 幂等放行 (已标 Stopped)
        if "404" not in exc.code:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"k8s delete HyperPodPyTorchJob failed: {exc.message}",
            ) from exc
    await audit_training(row, user, "training.stop")
    logger.info("training.stop.ok", id=str(id_), k8s_cr=row["k8s_job_name"])
    return row


async def audit_training(
    row: dict[str, Any],
    user: dict[str, Any] | None,
    operation: str,
    *,
    status_: str = "succeeded",
) -> None:
    """写一条训练任务操作审计 (append-only, 失败不阻塞主流程)。

    operation: training.create / training.delete
    scope_key 挂在所属 workspace 下 (admin 按 ws 查得到)。照 devinstance 范例。
    """
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
            target_type="training_job",
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
        logger.warning("training.audit_fail", op=operation,
                       id=str(row.get("id") or ""), err=str(exc))
