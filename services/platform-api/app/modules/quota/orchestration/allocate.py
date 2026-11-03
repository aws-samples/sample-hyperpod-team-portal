"""管理员分配 / 调整 / 回收 ComputeQuota (DDB-only).

两步:
1. 调 AWS HyperPod API
2. 回写 DDB Workspaces.sagemaker_compute_quota_id (走 ws_repo.update_workspace)
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.logging import get_logger
from app.modules.cluster import crud as cluster_crud
from app.modules.quota.api.schemas import (
    ComputeQuota,
    CreateComputeQuotaPayload,
    UpdateComputeQuotaPayload,
)
from app.modules.quota.response.builders import (
    aws_quota_to_schema,
    build_quota_config_payload,
)
from app.modules.quota.orchestration.workspace_quota import _tag_resource_pools
from app.modules.workspace import crud as workspace_crud
from app.repositories import workspaces as ws_repo
from app.services.hyperpod_client import HyperPodClient

logger = get_logger(__name__)


async def _get_workspace_or_404(db: Any, ws_id: Any) -> dict[str, Any]:
    del db
    ws = await workspace_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    return ws


async def create_workspace_quota(
    db: Any,
    hp: HyperPodClient,
    ws_id: Any,
    payload: CreateComputeQuotaPayload,
) -> ComputeQuota:
    del db
    ws = await _get_workspace_or_404(None, ws_id)
    cluster = await cluster_crud.get_cluster_by_id(None, ws.get("cluster_id"))
    if cluster is None or not cluster.get("hyperpod_cluster_arn"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"workspace {ws.get('name')} cluster has no hyperpod_cluster_arn",
        )

    aws_payload: dict[str, Any] = {
        "Name": payload.name,
        "ClusterArn": cluster["hyperpod_cluster_arn"],
        "ComputeQuotaConfig": build_quota_config_payload(
            payload.resources, payload.sharing_config, payload.preempt_team_tasks
        ),
        "ComputeQuotaTarget": {
            "TeamName": payload.target.team_name,
            "FairShareWeight": payload.target.fair_share_weight,
        },
        "ActivationState": payload.activation_state,
    }
    if payload.description:
        aws_payload["Description"] = payload.description

    created = await hp.create_compute_quota(aws_payload)
    quota_id = created["ComputeQuotaId"]
    quota_arn = created["ComputeQuotaArn"]

    # 回写 DDB Workspaces
    await ws_repo.update_workspace(
        str(ws.get("workspace_id") or ws.get("id")), compute_quota_id=quota_id
    )

    resp = await hp.describe_compute_quota(quota_id)
    logger.info(
        "quota.create.ok",
        ws_id=str(ws_id),
        quota_id=quota_id,
        team=payload.target.team_name,
        quota_arn=quota_arn,
    )
    schema = aws_quota_to_schema(resp)
    await _tag_resource_pools(schema)
    return schema


async def update_workspace_quota(
    db: Any,
    hp: HyperPodClient,
    ws_id: Any,
    payload: UpdateComputeQuotaPayload,
) -> ComputeQuota:
    del db
    ws = await _get_workspace_or_404(None, ws_id)
    quota_id = ws.get("sagemaker_compute_quota_id") or ws.get("compute_quota_id")
    if not quota_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"workspace {ws.get('name')} has no ComputeQuota bound yet",
        )

    current = await hp.describe_compute_quota(quota_id)
    cur_schema = aws_quota_to_schema(current)
    target_version = int(current.get("ComputeQuotaVersion") or 1)

    merged_resources = payload.resources or cur_schema.resources
    merged_sharing = payload.sharing_config or cur_schema.sharing_config
    merged_preempt = payload.preempt_team_tasks or cur_schema.preempt_team_tasks
    merged_target = payload.target or cur_schema.target
    merged_activation = payload.activation_state or cur_schema.activation_state
    merged_description = (
        payload.description
        if payload.description is not None
        else cur_schema.description
    )

    # 无变化短路 (AWS UpdateComputeQuota 对"数据与现有完全相同"会抛
    # ValidationException: The update data is the same as the existing one)。
    # 比对 merged 与当前值, 全部相同则视为幂等, 直接返回当前 quota, 不调 AWS。
    # (兜底: 即便此处比对漏字段, adapter 层 update_compute_quota 还会把该
    #  ValidationException 当成功处理。)
    unchanged = (
        merged_resources == cur_schema.resources
        and merged_sharing == cur_schema.sharing_config
        and merged_preempt == cur_schema.preempt_team_tasks
        and merged_target == cur_schema.target
        and merged_activation == cur_schema.activation_state
        and merged_description == cur_schema.description
    )
    if unchanged:
        logger.info(
            "quota.update.noop", ws_id=str(ws_id), quota_id=quota_id,
        )
        # tag 只在返回路径, 且必须在上面 unchanged 比对之后 (tag 会原地改
        # cur_schema.resources, 提前 tag 会破坏 merged==cur 的相等判断)。
        await _tag_resource_pools(cur_schema)
        return cur_schema

    aws_update: dict[str, Any] = {
        "ComputeQuotaConfig": build_quota_config_payload(
            merged_resources, merged_sharing, merged_preempt
        ),
        "ComputeQuotaTarget": {
            "TeamName": merged_target.team_name,
            "FairShareWeight": merged_target.fair_share_weight,
        },
        "ActivationState": merged_activation,
    }
    if merged_description:
        aws_update["Description"] = merged_description

    await hp.update_compute_quota(quota_id, target_version, aws_update)
    refreshed = await hp.describe_compute_quota(quota_id)
    logger.info(
        "quota.update.ok",
        ws_id=str(ws_id),
        quota_id=quota_id,
        from_version=target_version,
    )
    schema = aws_quota_to_schema(refreshed)
    await _tag_resource_pools(schema)
    return schema


async def delete_workspace_quota(
    db: Any,
    hp: HyperPodClient,
    ws_id: Any,
) -> None:
    del db
    ws = await _get_workspace_or_404(None, ws_id)
    quota_id = ws.get("sagemaker_compute_quota_id") or ws.get("compute_quota_id")
    if not quota_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"workspace {ws.get('name')} has no ComputeQuota bound yet",
        )

    await hp.delete_compute_quota(quota_id)

    # 清 DDB compute_quota_id (DDB SET 不支持 NULL; 用空字符串占位)
    await ws_repo.update_workspace(
        str(ws.get("workspace_id") or ws.get("id")), compute_quota_id=""
    )
    logger.info("quota.delete.ok", ws_id=str(ws_id), quota_id=quota_id)
