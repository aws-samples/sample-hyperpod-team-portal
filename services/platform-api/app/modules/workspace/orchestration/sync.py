"""Workspace ↔ AWS 一致性同步 (DDB-only).

只读快照, 不写库.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.logging import get_logger
from app.modules.workspace.persistence import crud
from app.services.hyperpod_client import HyperPodAPIError, HyperPodClient

logger = get_logger(__name__)


async def sync_workspace_from_aws(
    db: Any,
    ws_id: Any,
    hp_client: HyperPodClient,
) -> dict[str, Any]:
    """拉对应 AWS ComputeQuota 状态; 不修改任何数据."""
    del db
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )

    quota_id = ws.get("sagemaker_compute_quota_id") or ws.get("compute_quota_id")
    if not quota_id:
        return {
            "workspace_id": str(ws.get("id")),
            "aws_compute_quota_id": None,
            "aws_reachable": False,
            "aws_status": "missing",
            "name_mismatch": False,
            "arn_mismatch": False,
            "details": {},
        }

    try:
        aws_resp = await hp_client.describe_compute_quota(quota_id)
    except HyperPodAPIError as exc:
        logger.warning(
            "workspace.sync.aws_describe_fail",
            ws_id=str(ws_id),
            quota_id=quota_id,
            code=exc.code,
            msg=exc.message,
        )
        return {
            "workspace_id": str(ws.get("id")),
            "aws_compute_quota_id": quota_id,
            "aws_reachable": False,
            "aws_status": "unreachable",
            "name_mismatch": False,
            "arn_mismatch": False,
            "details": {"error_code": exc.code, "error_message": exc.message},
        }

    aws_team_name = (
        aws_resp.get("ComputeQuotaTarget", {}).get("TeamName")
        if isinstance(aws_resp.get("ComputeQuotaTarget"), dict)
        else None
    )
    aws_arn = aws_resp.get("ComputeQuotaArn")
    aws_status = aws_resp.get("ActivationState") or "unknown"

    return {
        "workspace_id": str(ws.get("id")),
        "aws_compute_quota_id": quota_id,
        "aws_reachable": True,
        "aws_status": aws_status,
        "name_mismatch": (
            aws_team_name != ws.get("name") if aws_team_name else False
        ),
        "arn_mismatch": (
            aws_arn != ws.get("sagemaker_compute_quota_arn") if aws_arn else False
        ),
        "details": {
            "team_name": aws_team_name,
            "compute_quota_arn": aws_arn,
            "activation_state": aws_status,
        },
    }
