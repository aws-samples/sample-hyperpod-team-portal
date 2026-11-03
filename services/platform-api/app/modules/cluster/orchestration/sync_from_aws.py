"""AWS 侧数据抓取 (DDB-only).

历史: 原本同时负责拉 AWS describe_cluster + 写 RDS instance_group 表.
现在 RDS 已不存在; 数据 100% 从 AWS adapter 取, 不再 upsert DB.

只保留 ``describe_cluster_live`` / ``list_cluster_nodes_live`` 两个
safe 包装器供 ``get_summary`` / ``sync_cluster`` 共享.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.hyperpod_client import HyperPodAPIError, HyperPodClient

logger = get_logger(__name__)


async def describe_cluster_live(
    hp_client: HyperPodClient,
    cluster_name: str,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    """安全调 describe_cluster; 失败写 errors 并返 None."""
    try:
        return await hp_client.describe_cluster(cluster_name)
    except HyperPodAPIError as exc:
        logger.warning(
            "cluster.aws.describe.fail", cluster=cluster_name, code=exc.code
        )
        errors.append(
            {"op": "describe_cluster", "code": exc.code, "message": exc.message}
        )
        return None


async def list_cluster_nodes_live(
    hp_client: HyperPodClient,
    cluster_name: str,
    errors: list[dict[str, str]],
) -> list[dict[str, Any]] | None:
    """安全调 list_cluster_nodes; 失败写 errors 并返 None."""
    try:
        return await hp_client.list_cluster_nodes(cluster_name)
    except HyperPodAPIError as exc:
        logger.warning(
            "cluster.aws.list_nodes.fail", cluster=cluster_name, code=exc.code
        )
        errors.append(
            {"op": "list_cluster_nodes", "code": exc.code, "message": exc.message}
        )
        return None
