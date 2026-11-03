"""K8s 侧数据抓取 (DDB-only).

历史: 拉 K8s Node 列表 + upsert RDS node_status. 切 DDB 后 RDS 没了,
node_status 数据 100% 实时从 AWS + K8s adapters 拉, 不再落 DB.

仅保留 ``list_k8s_nodes`` safe 包装供监控用.
"""

from __future__ import annotations

from typing import Any

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.logging import get_logger

logger = get_logger(__name__)


async def list_k8s_nodes(
    k8s_client: K8sClient,
    errors: list[dict[str, str]],
) -> list[dict[str, Any]] | None:
    """安全调 K8s list_nodes; 失败写 errors 并返 None."""
    try:
        return await k8s_client.list_nodes()
    except K8sAPIError as exc:
        logger.warning("cluster.k8s.list_nodes.fail", code=exc.code)
        errors.append(
            {"op": "k8s_list_nodes", "code": exc.code, "message": exc.message}
        )
        return None
