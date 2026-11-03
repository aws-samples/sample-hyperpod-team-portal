"""sync_cluster (DDB-only).

历史: AWS + K8s → RDS 幂等 upsert 顶层编排. RDS 没了, 此函数退化为
"返回 AWS + K8s 当前快照" 的轻量调用, 不再写持久层.

保留 sync_cluster 名字是因为外部 router 还在调.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.k8s import K8sClient
from app.core.logging import get_logger
from app.modules.cluster.orchestration.sync_from_aws import (
    describe_cluster_live,
    list_cluster_nodes_live,
)
from app.modules.cluster.orchestration.sync_from_k8s import list_k8s_nodes
from app.modules.cluster.persistence import crud
from app.services.hyperpod_client import HyperPodClient

logger = get_logger(__name__)


async def sync_cluster(
    db: Any,
    cluster_tag: str,
    hp_client: HyperPodClient,
    k8s_client: K8sClient,
) -> dict[str, Any]:
    """读 AWS + K8s 快照. DDB 模式下不再 upsert 任何 DB.

    Raises:
        ValueError: cluster_tag 不存在 (router 转 404).
    """
    del db
    cluster = await crud.get_cluster_by_tag(None, cluster_tag)
    if cluster is None:
        raise ValueError(f"cluster not found: {cluster_tag}")

    errors: list[dict[str, str]] = []
    synced_at = datetime.now(UTC)

    aws_describe = await describe_cluster_live(hp_client, cluster_tag, errors)
    aws_nodes = await list_cluster_nodes_live(hp_client, cluster_tag, errors)
    k8s_nodes = await list_k8s_nodes(k8s_client, errors)

    return {
        "cluster_tag": cluster_tag,
        "synced_at": synced_at.isoformat(),
        "instance_groups": {
            "upserted": 0,
            "deleted": 0,
            "note": "DDB-only: not persisted, AWS is source-of-truth",
        },
        "nodes": {
            "upserted": 0,
            "deleted": 0,
            "ready": sum(1 for n in (k8s_nodes or []) if n.get("ready")),
            "notready": sum(1 for n in (k8s_nodes or []) if not n.get("ready")),
        },
        "aws_raw": {
            "cluster_status": (aws_describe or {}).get("ClusterStatus"),
            "ig_count": len((aws_describe or {}).get("InstanceGroups") or []),
            "node_count": len(aws_nodes) if aws_nodes is not None else 0,
        },
        "k8s_raw": {
            "node_count": len(k8s_nodes) if k8s_nodes is not None else 0,
            "ready_count": sum(1 for n in (k8s_nodes or []) if n.get("ready")),
        },
        "errors": errors,
    }
