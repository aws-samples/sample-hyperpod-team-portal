"""SSM adapter (aioboto3) · 仅做 sidecar SSM activation 注册流程.

为什么后端要主动调 SSM: spaces operator v0.1.5 sidecar 设计是被动等
controller 推 activation, 而 controller 又等 deployment ready, sidecar 又
要 SSM 注册成功才 ready, 死锁.
"""

from __future__ import annotations

from typing import Any

import aioboto3

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def create_activation(description: str) -> dict[str, Any]:
    """创建 SSM Activation 拿到一对 (ActivationId, ActivationCode).

    :param description: 该 activation 的人类可读描述, 落到 SSM 控制台.
    :return: {"activation_id": str, "activation_code": str}

    raises:
        RuntimeError: settings.ssm_managed_node_role_arn 没配
        botocore.exceptions.ClientError: SSM API 失败 (上层兜底).
    """
    settings = get_settings()
    role_arn = settings.ssm_managed_node_role_arn.strip()
    if not role_arn:
        raise RuntimeError(
            "ssm_managed_node_role_arn not configured (check .env "
            "SSM_MANAGED_NODE_ROLE_ARN)"
        )
    # SSM CreateActivation IamRole 入参要 role name (不是 ARN, ≤64 char,
    # 不允许 ":"). 从 ARN 截尾.
    role_name = role_arn.split("/")[-1] if "/" in role_arn else role_arn

    session = aioboto3.Session(profile_name=settings.aws_profile) if settings.aws_profile else aioboto3.Session()

    async with session.client("ssm", region_name=settings.aws_region) as ssm:
        resp = await ssm.create_activation(
            IamRole=role_name,
            Description=description[:256],  # SSM 限 256 字符
            RegistrationLimit=1,
        )
        logger.info(
            "ssm.create_activation.ok",
            activation_id=resp["ActivationId"],
            description=description[:80],
        )
        return {
            "activation_id": resp["ActivationId"],
            "activation_code": resp["ActivationCode"],
        }


async def deregister_managed_instance(instance_id: str) -> None:
    """删 SSM 注册条目 (mi-xxx). 失败不抛, 只 logger.

    开发机删除时配合调用, 防止 mi-xxx 累积占 advanced tier 配额.
    """
    if not instance_id or not instance_id.startswith("mi-"):
        return
    settings = get_settings()
    session = (
        aioboto3.Session(profile_name=settings.aws_profile)
        if settings.aws_profile
        else aioboto3.Session()
    )
    try:
        async with session.client("ssm", region_name=settings.aws_region) as ssm:
            await ssm.deregister_managed_instance(InstanceId=instance_id)
            logger.info("ssm.deregister.ok", instance_id=instance_id)
    except Exception as exc:  # noqa: BLE001
        # InvalidInstanceId (已删) / 网络错误等不阻塞 K8s 删除流程
        logger.info(
            "ssm.deregister.skip", instance_id=instance_id, err=str(exc)
        )
