"""Workspace 生命周期流 (DDB-only).

delete_workspace_flow:
    AWS 先 → DDB 后. AWS NotFound 容忍.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import eks_pod_identity
from app.adapters.aws.eks_pod_identity import EksPodIdentityAPIError
from app.adapters.ddb import tables as ddb_tables
from app.adapters.k8s import K8sClient
from app.core.config import get_settings
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.workspace.api.schemas import MemberResponse, WorkspaceUpdate
from app.modules.workspace.domain.aws_team_mapping import is_aws_not_found_error
from app.modules.workspace.persistence import crud
from app.repositories import audit_log as audit_repo
from app.services.hyperpod_client import HyperPodAPIError, HyperPodClient

logger = get_logger(__name__)


# ===== Workspace =====

async def update_workspace_flow(
    db: Any, ws_id: Any, payload: WorkspaceUpdate
) -> dict[str, Any]:
    del db
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    return await crud.update_workspace(
        None,
        ws,
        display_name=payload.display_name,
        description=payload.description,
    )


async def delete_workspace_flow(
    db: Any,
    ws_id: Any,
    hp_client: HyperPodClient,
    current_user: dict[str, Any] | None = None,
    k8s_client: K8sClient | None = None,
) -> None:
    """硬删 — 级联清: K8s (PV/PVC/SA/Role/RoleBinding) + Pod Identity Assoc
    + AWS ComputeQuota + DDB 行 + 写 AuditLog.

    顺序:
      1. K8s: 删 ws ns 内所有 PV/PVC (FSx 挂载) + SA + Role + RoleBinding
      2. EKS: 删 Pod Identity Association
      3. AWS: 删 ComputeQuota (这一步会触发 HyperPod taskgovernance 清 namespace
         + Kueue queue, 但实测可能 namespace 残留 — Phase 1 不主动删 ns,
         仅清 ns 内的资源)
      4. DDB: 删 ws 行
      5. AuditLog: 写一行
    """
    del db
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")

    settings = get_settings()
    namespace = ws.get("namespace") or (ws.get("metadata_json") or {}).get("namespace")
    metadata = ws.get("metadata_json") or {}
    fsx_mounts = metadata.get("fsx_mounts") or []
    pod_identity_assoc_id = metadata.get("pod_identity_association_id")
    quota_id = ws.get("sagemaker_compute_quota_id") or ws.get("compute_quota_id")

    # ===== 1. K8s 资源清理 (尽力清, 单项失败只 log) =====
    k8s = k8s_client or K8sClient(context=settings.kube_context or None)
    if namespace:
        # 1a. 删 PVC + PV (按 metadata 里记录的)
        for mount in fsx_mounts:
            pvc = mount.get("pvc_name")
            pv = mount.get("pv_name")
            if pvc:
                try:
                    await k8s.delete_pvc(namespace, pvc)
                except Exception as exc:
                    logger.warning(
                        "workspace.delete.pvc_fail",
                        ns=namespace, pvc=pvc, err=str(exc),
                    )
            if pv:
                try:
                    await k8s.delete_pv(pv)
                except Exception as exc:
                    logger.warning(
                        "workspace.delete.pv_fail",
                        pv=pv, err=str(exc),
                    )
        # 1b. 删 RoleBinding + Role
        try:
            await k8s.delete_workspace_role_and_binding(namespace)
        except Exception as exc:
            logger.warning(
                "workspace.delete.role_fail", ns=namespace, err=str(exc)
            )
        # 1c. 删 SA
        try:
            await k8s.delete_workspace_service_account(namespace)
        except Exception as exc:
            logger.warning(
                "workspace.delete.sa_fail", ns=namespace, err=str(exc)
            )

    # ===== 2. Pod Identity Association =====
    if pod_identity_assoc_id and settings.eks_cluster_name:
        try:
            await eks_pod_identity.delete_association(
                cluster_name=settings.eks_cluster_name,
                association_id=pod_identity_assoc_id,
            )
        except EksPodIdentityAPIError as exc:
            logger.warning(
                "workspace.delete.pod_identity_fail",
                association_id=pod_identity_assoc_id,
                err=str(exc),
            )

    # ===== 3. AWS ComputeQuota =====
    if quota_id:
        try:
            await hp_client.delete_compute_quota(quota_id)
            logger.info(
                "workspace.delete.aws_quota_ok",
                ws_id=str(ws_id),
                quota_id=quota_id,
            )
        except HyperPodAPIError as exc:
            if is_aws_not_found_error(exc.code, exc.message):
                logger.info(
                    "workspace.delete.aws_quota_already_gone",
                    ws_id=str(ws_id),
                    quota_id=quota_id,
                    code=exc.code,
                )
            else:
                logger.warning(
                    "workspace.delete.aws_quota_fail",
                    ws_id=str(ws_id),
                    quota_id=quota_id,
                    code=exc.code,
                    msg=exc.message,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        f"AWS DeleteComputeQuota failed [{exc.code}]: {exc.message}"
                    ),
                ) from exc

    # ===== 4. DDB =====
    await crud.delete_workspace(None, ws)
    logger.info(
        "workspace.delete.ok",
        ws_id=str(ws_id),
        name=ws.get("name"),
        namespace=ws.get("namespace"),
        actor=(current_user or {}).get("username"),
    )

    # AuditLog · append-only
    actor = current_user or {}
    actor_username = str(actor.get("username") or actor.get("user_id") or "")
    try:
        await audit_repo.append(
            scope_key=ddb_tables.scope_key_workspace(str(ws_id)),
            actor_user_id=actor_username,
            actor_role="platform-admin",
            operation="workspace.delete",
            target_type="workspace",
            target_id=str(ws_id),
            status="succeeded",
            metadata={
                "name": ws.get("name") or "",
                "namespace": ws.get("namespace") or "",
                "compute_quota_id": quota_id or "",
                "actor_email": actor.get("email") or "",
                "actor_display_name": actor.get("display_name") or "",
            },
        )
    except Exception as audit_exc:  # pragma: no cover - 审计失败不影响主流程
        logger.warning(
            "workspace.delete.audit_fail",
            ws_id=str(ws_id),
            err=str(audit_exc),
        )


# ===== Member =====

def _assert_member_action_allowed(
    actor: dict[str, Any], target_user_id: str, new_role: str | None
) -> None:
    """ws 管理员不能对自己执行移除 / 降级; 平台超管不受限。

    new_role=None 表示移除操作; new_role="member" 表示降级; 其余角色变更放行。
    """
    if actor.get("is_admin") is True:
        return  # 平台超管代理能力, 不受限
    actor_id = str(actor.get("username") or actor.get("user_id") or "")
    if actor_id and actor_id == str(target_user_id):
        if new_role is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, t("workspace.cannot_remove_self"))
        if new_role == "member":
            raise HTTPException(status.HTTP_403_FORBIDDEN, t("workspace.cannot_demote_self"))


async def update_member_role_flow(
    db: Any, ws_id: Any, user_id: Any, role: str, actor: dict[str, Any]
) -> MemberResponse:
    """更新成员角色.

    PR feat/no-users-table-username-as-id, 2026-05-20:
        - user_id 语义 = IdC username
        - 不再 lookup users_repo, email/display_name 直接从 membership 行的冗余字段读
    """
    del db
    membership = await crud.get_membership(None, ws_id, user_id)
    if membership is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"membership not found: ws={ws_id} user={user_id}",
        )
    _assert_member_action_allowed(actor, str(user_id), new_role=role)
    membership = await crud.update_membership_role(None, membership, role)
    return MemberResponse(
        user_id=str(membership.get("username") or membership.get("user_id") or user_id),
        email=membership.get("email") or "",
        display_name=membership.get("display_name") or "",
        role=membership["role"],  # type: ignore[arg-type]
        joined_at=membership.get("joined_at") or "",
    )


async def remove_member_flow(
    db: Any, ws_id: Any, user_id: Any, actor: dict[str, Any]
) -> None:
    del db
    membership = await crud.get_membership(None, ws_id, user_id)
    if membership is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"membership not found: ws={ws_id} user={user_id}",
        )
    _assert_member_action_allowed(actor, str(user_id), new_role=None)
    await crud.delete_membership(None, membership)

    # 级联删该用户在本 ws 的所有 FSx 挂载授权 (设计 §5.4)
    from app.repositories import mount_permissions as mount_perms_repo

    try:
        deleted = await mount_perms_repo.delete_by_user_in_ws(
            str(ws_id), str(user_id)
        )
        logger.info(
            "workspace.member.remove.perms_cascaded",
            ws_id=ws_id, username=user_id, count=deleted,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workspace.member.remove.perms_cascade_fail",
            ws_id=ws_id, username=user_id, err=str(exc),
        )
