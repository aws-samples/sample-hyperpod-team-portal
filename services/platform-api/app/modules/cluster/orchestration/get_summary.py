"""cluster summary (DDB-only).

历史: 合并 RDS + AWS + quota. 切 DDB 后, RDS 不存在; cluster / IG /
node 都直接走 AWS adapters 即可.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.modules.cluster.domain.health_check import derive_sync_status
from app.modules.cluster.orchestration.sync_from_aws import (
    describe_cluster_live,
    list_cluster_nodes_live,
)
from app.modules.cluster.persistence import crud
from app.modules.cluster.response.builders import (
    build_cluster_info,
    build_quotas_flat_list,
)
from app.services.hyperpod_client import HyperPodClient


async def get_cluster_summary(
    db: Any,
    cluster_tag: str,
    hp_client: HyperPodClient,
) -> dict[str, Any] | None:
    """合并 AWS 活数据 + ComputeQuota; cluster 不存在 → None."""
    del db
    cluster = await crud.get_cluster_by_tag(None, cluster_tag)
    if cluster is None:
        return None

    errors: list[dict[str, str]] = []
    pseudo_id = cluster.get("id")

    db_summary_task = crud.get_cluster_summary_aggregated(None, pseudo_id)
    quotas_task = crud.list_resource_quotas(None, pseudo_id)

    if cluster.get("type") == "hyperpod":
        db_summary, quotas_dicts, aws_describe, aws_nodes = await asyncio.gather(
            db_summary_task,
            quotas_task,
            describe_cluster_live(hp_client, cluster_tag, errors),
            list_cluster_nodes_live(hp_client, cluster_tag, errors),
        )
    else:
        db_summary, quotas_dicts = await asyncio.gather(db_summary_task, quotas_task)
        aws_describe = None
        aws_nodes = None

    metadata = cluster.get("metadata_json") or {}
    advanced_features = metadata.get("advanced_features", {})

    instance_groups_db = [
        {
            "group_name": ig.group_name,
            "instance_type": ig.instance_type,
            "count": ig.count,
            "target": ig.target,
            "az": ig.az,
            "gpus_total": ig.gpus_total,
            "gpus_used": ig.gpus_used,
            "gpus_pending": ig.gpus_pending,
            "nodes_schedulable": ig.nodes_schedulable,
            "nodes_unhealthy": ig.nodes_unhealthy,
            "nodes_cordoned": ig.nodes_cordoned,
            "nodes_replacing": ig.nodes_replacing,
        }
        for ig in (db_summary.instance_groups if db_summary else [])
    ]

    instance_groups_live = (aws_describe or {}).get("InstanceGroups", []) or []

    nodes_db_count = 0
    if db_summary:
        nodes_db_count = (
            db_summary.totals.nodes_ready + db_summary.totals.nodes_unhealthy
        )
    nodes_live_count = len(aws_nodes) if aws_nodes is not None else 0

    health = {
        "ready": db_summary.totals.nodes_ready if db_summary else 0,
        "notready": db_summary.totals.nodes_unhealthy if db_summary else 0,
        "unknown": 0,
        "total": nodes_db_count,
    }

    sync_status = derive_sync_status(
        cluster_type=cluster.get("type") or "unknown",
        db_ig_count=len(instance_groups_db),
        aws_ig_count=len(instance_groups_live) if aws_describe else None,
        had_aws_error=bool(errors),
    )

    return {
        "cluster": build_cluster_info(cluster),
        "instance_groups_db": instance_groups_db,
        "instance_groups_live": instance_groups_live,
        "nodes_db_count": nodes_db_count,
        "nodes_live_count": nodes_live_count,
        "health": health,
        "quotas": build_quotas_flat_list(quotas_dicts),
        "advanced_features": advanced_features,
        "sync_status": sync_status,
        "errors": errors,
    }
