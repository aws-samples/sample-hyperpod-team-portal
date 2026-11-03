"""Kueue 实时用量同步 (原 quota_usage/service.py 主逻辑).

职责:
- 按 workspace.name 推 ClusterQueue 名字
- 调 KueueClient 拉 status
- 走 domain.allocation.parse_cluster_queue_status 解析

纯解析逻辑留在 domain/allocation.py, 这里只做 IO 编排.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.quota.api.schemas import QuotaUsage
from app.modules.quota.domain.allocation import parse_cluster_queue_status
from app.services.kueue_client import KueueClient

logger = get_logger(__name__)


async def fetch_quota_usage(workspace_name: str) -> QuotaUsage:
    """按 workspace.name 拉 Kueue ClusterQueue.status 返 QuotaUsage.

    ClusterQueue naming convention (真实集群已验证):
        hyperpod-ns-{workspace.name}-clusterqueue

    查不到 CR 返空 resources 的 QuotaUsage (不造假, 打 warning 日志).
    """
    cq_name = f"hyperpod-ns-{workspace_name}-clusterqueue"
    kueue = KueueClient(context=get_settings().kube_context or None)
    status = await kueue.get_cluster_queue_status(cq_name)
    if status is None:
        logger.warning("quota_usage.cluster_queue.missing", cq=cq_name)
    return parse_cluster_queue_status(workspace_name, status)
