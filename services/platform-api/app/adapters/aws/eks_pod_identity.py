"""AWS EKS Pod Identity Association adapter.

职责:
    把 ws ns 的 ServiceAccount workspace-default 关联到 platform-pod-role,
    pod 起来后通过 Pod Identity Agent 拿到 role 的临时 credential.

API:
    eks:CreatePodIdentityAssociation / DeletePodIdentityAssociation /
    ListPodIdentityAssociations

"""

from __future__ import annotations

from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EksPodIdentityAPIError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


async def create_association(
    *,
    cluster_name: str,
    namespace: str,
    service_account: str,
    role_arn: str,
) -> dict[str, Any]:
    """关联 SA → IAM role. 返回 association id + arn.

    幂等性: AWS 不接受同 ns+sa 的二次 create (会报 ResourceInUseException).
    调用方应 catch 后视为成功.
    """
    s = get_settings()
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )
    try:
        async with session.client("eks", region_name=s.aws_region) as client:
            resp = await client.create_pod_identity_association(
                clusterName=cluster_name,
                namespace=namespace,
                serviceAccount=service_account,
                roleArn=role_arn,
            )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise EksPodIdentityAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise EksPodIdentityAPIError("BotoCoreError", str(exc)) from exc

    assoc = resp.get("association") or {}
    logger.info(
        "eks.pod_identity.association.created",
        cluster=cluster_name,
        ns=namespace,
        sa=service_account,
        association_id=assoc.get("associationId"),
    )
    return {
        "association_id": assoc.get("associationId"),
        "association_arn": assoc.get("associationArn"),
        "namespace": assoc.get("namespace"),
        "service_account": assoc.get("serviceAccount"),
        "role_arn": assoc.get("roleArn"),
    }


async def delete_association(
    *,
    cluster_name: str,
    association_id: str,
) -> None:
    """删 Pod Identity Association. NotFound 容忍."""
    s = get_settings()
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )
    try:
        async with session.client("eks", region_name=s.aws_region) as client:
            await client.delete_pod_identity_association(
                clusterName=cluster_name,
                associationId=association_id,
            )
    except ClientError as exc:
        err = exc.response.get("Error", {})
        if err.get("Code") in ("ResourceNotFoundException", "NotFoundException"):
            logger.info(
                "eks.pod_identity.association.already_gone",
                cluster=cluster_name,
                association_id=association_id,
            )
            return
        raise EksPodIdentityAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise EksPodIdentityAPIError("BotoCoreError", str(exc)) from exc

    logger.info(
        "eks.pod_identity.association.deleted",
        cluster=cluster_name,
        association_id=association_id,
    )


async def list_associations_in_namespace(
    *,
    cluster_name: str,
    namespace: str,
) -> list[dict[str, Any]]:
    """列指定 ns 下所有 association. 删 ws 时反查用 (找 association_id 删).

    分页聚合.
    """
    s = get_settings()
    session = aioboto3.Session(
        profile_name=s.aws_profile or None, region_name=s.aws_region
    )
    out: list[dict[str, Any]] = []
    next_token: str | None = None

    try:
        async with session.client("eks", region_name=s.aws_region) as client:
            while True:
                kwargs: dict[str, Any] = {
                    "clusterName": cluster_name,
                    "namespace": namespace,
                }
                if next_token:
                    kwargs["nextToken"] = next_token
                resp = await client.list_pod_identity_associations(**kwargs)
                for a in resp.get("associations") or []:
                    out.append(
                        {
                            "association_id": a.get("associationId"),
                            "association_arn": a.get("associationArn"),
                            "namespace": a.get("namespace"),
                            "service_account": a.get("serviceAccount"),
                        }
                    )
                next_token = resp.get("nextToken")
                if not next_token:
                    break
    except ClientError as exc:
        err = exc.response.get("Error", {})
        raise EksPodIdentityAPIError(
            err.get("Code", "Unknown"), err.get("Message", str(exc))
        ) from exc
    except BotoCoreError as exc:
        raise EksPodIdentityAPIError("BotoCoreError", str(exc)) from exc

    return out
