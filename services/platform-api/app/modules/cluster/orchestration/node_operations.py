"""节点操作编排 (DDB-only).

历史: 写 RDS node_operation_log + (M2 待) 调 HyperPod. 切 DDB 后, 审计
落 ``DDB AuditLog`` (scope='cluster#<id>'). API 不变.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.cluster.persistence import crud
from app.services.hyperpod_client import HyperPodAPIError, HyperPodClient

logger = get_logger(__name__)


async def reboot_node(
    db: Any,
    cluster_tag: str,
    node_name: str,
    actor_user_id: Any,
    actor_role: str,
    reason: str | None,
    hp_client: HyperPodClient,
) -> dict[str, Any]:
    return await _submit_node_op(
        db=db,
        cluster_tag=cluster_tag,
        node_name=node_name,
        operation="reboot",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
        hp_client=hp_client,
    )


async def replace_node(
    db: Any,
    cluster_tag: str,
    node_name: str,
    actor_user_id: Any,
    actor_role: str,
    reason: str | None,
    hp_client: HyperPodClient,
) -> dict[str, Any]:
    return await _submit_node_op(
        db=db,
        cluster_tag=cluster_tag,
        node_name=node_name,
        operation="replace",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
        hp_client=hp_client,
    )


async def delete_node(
    db: Any,
    cluster_tag: str,
    node_name: str,
    actor_user_id: Any,
    actor_role: str,
    reason: str | None,
    hp_client: HyperPodClient,
) -> dict[str, Any]:
    return await _submit_node_op(
        db=db,
        cluster_tag=cluster_tag,
        node_name=node_name,
        operation="delete",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
        hp_client=hp_client,
    )


async def _submit_node_op(
    db: Any,
    cluster_tag: str,
    node_name: str,
    operation: str,
    actor_user_id: Any,
    actor_role: str,
    reason: str | None,
    hp_client: HyperPodClient,
) -> dict[str, Any]:
    del db
    cluster = await crud.get_cluster_by_tag(None, cluster_tag)
    if cluster is None:
        raise ValueError(f"cluster not found: {cluster_tag}")

    await crud.log_node_operation(
        db=None,
        cluster_id=cluster["id"],
        node_name=node_name,
        operation=operation,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
        aws_request_id=None,
        status="submitted",
    )

    logger.info(
        "cluster.node_op.submitted",
        cluster=cluster_tag,
        node=node_name,
        op=operation,
        actor=str(actor_user_id),
    )
    _ = hp_client  # M2 实装

    return {
        "cluster_tag": cluster_tag,
        "node_name": node_name,
        "operation": operation,
        "status": "submitted",
        "note": "node operation queued · actual AWS call pending M2",
    }


async def scale_instance_group(
    db: Any,
    cluster_tag: str,
    group_name: str,
    target_count: int,
    actor_user_id: Any,
    actor_role: str,
    reason: str | None,
    hp_client: HyperPodClient,
) -> dict[str, Any]:
    del db
    cluster = await crud.get_cluster_by_tag(None, cluster_tag)
    if cluster is None:
        raise ValueError(f"cluster not found: {cluster_tag}")

    logger.info(
        "cluster.ig_scale.submitted",
        cluster=cluster_tag,
        group=group_name,
        target=target_count,
        actor=str(actor_user_id),
        reason=reason,
        role=actor_role,
    )
    _ = hp_client  # M2 实装
    return {
        "cluster_tag": cluster_tag,
        "group_name": group_name,
        "target_count": target_count,
        "status": "submitted",
        "note": "scale operation queued · actual AWS call pending M2",
    }


_ = HyperPodAPIError
