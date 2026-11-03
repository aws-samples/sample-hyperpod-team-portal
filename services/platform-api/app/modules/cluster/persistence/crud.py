"""集群 CRUD — DDB-only / AWS-as-SoT.

历史: 原本是 RDS SQLAlchemy 多表聚合查询 (cluster + instance_group +
node_status + resource_quota + node_operation_log).

现在:
- cluster / IG / node 数据 100% 来自 AWS DescribeCluster + ListClusterNodes
- ResourceQuota 来自 AWS DescribeComputeQuota
- NodeOperationLog 改写到 DDB AuditLog (scope='cluster#<id>')

签名兼容性:
    全部接口的 ``db`` 参数保留但被忽略 (调用方仍在传).
    cluster_id 改用 ``cluster_tag`` 字符串 (AWS ClusterName).
    返回 dict (non-ORM); 通过 ``id`` alias 兼容旧调用.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from app.adapters.aws import cluster_describe, compute_quota, nodes
from app.repositories import audit_log as audit_repo


def _cluster_pseudo_id(cluster_tag: str) -> str:
    """Stable pseudo-UUID for a cluster_tag (AWS-only side).

    历史调用方期望 ``cluster.id`` 是 UUID. 我们没有 RDS 行了, 用
    UUID5 把 cluster_tag 映射到稳定 UUID 作为 id 字段.
    """
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"hyperpod://cluster/{cluster_tag}"))


def _to_cluster_dict(summary: dict[str, Any]) -> dict[str, Any]:
    """AWS get_cluster_summary 输出 → 业务 cluster dict.

    填补 id / workspace_scope / metadata_json / last_synced_at 字段
    保持下游 schema (ClusterSummary / cluster_info) 不破.
    """
    tag = summary.get("cluster_tag") or "unknown"
    out = dict(summary)
    out["id"] = _cluster_pseudo_id(tag)
    out.setdefault("workspace_scope", "shared")
    out.setdefault("metadata_json", {})
    out.setdefault("last_synced_at", None)
    return out


# =====================================================================
# 基础 CRUD (db 参数保留但忽略)
# =====================================================================

async def get_cluster_by_id(db: Any, cluster_id: Any) -> dict[str, Any] | None:
    """按 pseudo-id (UUID5) 反查 cluster.

    M1 简化: 仅支持 settings.hyperpod_cluster_name 这一个集群; 任何
    传入的 cluster_id 都返回该集群 (RDS 时代多集群业务暂不开).
    """
    del db
    cid_str = str(cluster_id)
    try:
        summary = await cluster_describe.get_cluster_summary()
    except Exception:
        return None
    out = _to_cluster_dict(summary)
    if out["id"] != cid_str:
        # 可能是历史 UUID (RDS 期). 仍返回唯一可用 cluster.
        out["id"] = cid_str
    return out


async def get_cluster_by_tag(db: Any, cluster_tag: str) -> dict[str, Any] | None:
    del db
    try:
        summary = await cluster_describe.get_cluster_summary(cluster_tag)
    except Exception:
        return None
    return _to_cluster_dict(summary)


async def list_clusters(
    db: Any, type_filter: str | None = None
) -> list[dict[str, Any]]:
    """单集群部署: M1 仅返回当前 settings.hyperpod_cluster_name 一个."""
    del db
    try:
        summary = await cluster_describe.get_cluster_summary()
    except Exception:
        return []
    out = _to_cluster_dict(summary)
    if type_filter and out.get("type") != type_filter:
        return []
    return [out]


# =====================================================================
# 1) get_cluster_summary_aggregated (退化版)
# =====================================================================

@dataclass(slots=True)
class InstanceGroupSummaryDTO:
    group_name: str
    instance_type: str
    count: int
    target: int
    az: str
    gpus_total: int
    gpus_used: int
    gpus_pending: int
    nodes_schedulable: int
    nodes_unhealthy: int
    nodes_cordoned: int
    nodes_replacing: int


@dataclass(slots=True)
class ClusterTotalsDTO:
    nodes_ready: int
    nodes_unhealthy: int
    gpus_total: int
    gpus_used: int
    gpus_used_pct: float
    active_workspaces: int
    active_training_jobs: int = 0
    active_inference_services: int = 0


@dataclass(slots=True)
class ClusterSummaryAggregated:
    cluster: dict[str, Any]
    instance_groups: list[InstanceGroupSummaryDTO]
    totals: ClusterTotalsDTO


async def get_cluster_summary_aggregated(
    db: Any, cluster_id: Any
) -> ClusterSummaryAggregated | None:
    """从 AWS 拉 IG/Node + 业务字段聚合.

    GPU 用量 / pending 数据精确度依赖 K8s metrics, 此处给降级口径
    (gpus_used = 0, pending = 0). 真正的 K8s 集成在 M2 的
    monitoring 模块负责.
    """
    del db
    cluster = await get_cluster_by_id(None, cluster_id)
    if cluster is None:
        return None

    igs_aws = await cluster_describe.list_instance_groups()
    nodes_aws = await nodes.list_cluster_nodes()

    nodes_by_ig: dict[str, list[dict[str, Any]]] = {}
    for n in nodes_aws:
        ig_name = n.get("InstanceGroupName") or "unknown"
        nodes_by_ig.setdefault(ig_name, []).append(n)

    ig_dtos: list[InstanceGroupSummaryDTO] = []
    nodes_ready_total = 0
    nodes_unhealthy_total = 0
    gpus_total_all = 0

    for ig in igs_aws:
        name = ig.get("InstanceGroupName") or "unknown"
        ig_nodes = nodes_by_ig.get(name, [])
        sch = sum(
            1 for n in ig_nodes if n.get("InstanceStatus", {}).get("Status") == "Running"
        )
        unh = sum(
            1
            for n in ig_nodes
            if n.get("InstanceStatus", {}).get("Status")
            in ("Failure", "Unhealthy")
        )
        nodes_ready_total += sch
        nodes_unhealthy_total += unh

        ig_dtos.append(
            InstanceGroupSummaryDTO(
                group_name=name,
                instance_type=ig.get("InstanceType") or "unknown",
                count=int(ig.get("CurrentCount") or 0),
                target=int(ig.get("TargetCount") or 0),
                az="us-west-2a",  # AWS describe 不直接给 IG az; 上层取 vpc.subnets[0]
                gpus_total=0,  # 需 K8s allocatable 才能算
                gpus_used=0,
                gpus_pending=0,
                nodes_schedulable=sch,
                nodes_unhealthy=unh,
                nodes_cordoned=0,
                nodes_replacing=0,
            )
        )

    totals = ClusterTotalsDTO(
        nodes_ready=nodes_ready_total,
        nodes_unhealthy=nodes_unhealthy_total,
        gpus_total=gpus_total_all,
        gpus_used=0,
        gpus_used_pct=0.0,
        active_workspaces=0,
    )

    return ClusterSummaryAggregated(
        cluster=cluster, instance_groups=ig_dtos, totals=totals
    )


# =====================================================================
# 2) get_nodes_with_workloads (退化版 - AWS 节点)
# =====================================================================

@dataclass(slots=True)
class NodeListFilters:
    instance_group: str | None = None
    health_status: str | None = None
    gpu_type: str | None = None
    workspace: str | None = None
    cursor: str | None = None
    page_size: int = 20


@dataclass(slots=True)
class NodeListPage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool


async def get_nodes_with_workloads(
    db: Any, cluster_id: Any, filters: NodeListFilters
) -> NodeListPage:
    """从 AWS list_cluster_nodes 列节点 + Python 侧 filter 简化版."""
    del db, cluster_id
    rows = await nodes.list_cluster_nodes()
    if filters.instance_group:
        rows = [
            n for n in rows if n.get("InstanceGroupName") == filters.instance_group
        ]
    rows = sorted(rows, key=lambda n: n.get("InstanceId") or "")

    if filters.cursor:
        rows = [n for n in rows if (n.get("InstanceId") or "") > filters.cursor]
    has_more = len(rows) > filters.page_size
    items = rows[: filters.page_size]
    next_cursor = (
        items[-1].get("InstanceId") if has_more and items else None
    )
    return NodeListPage(items=items, next_cursor=next_cursor, has_more=has_more)


# =====================================================================
# 3) list_resource_quotas — 走 AWS ComputeQuota
# =====================================================================

async def list_resource_quotas(
    db: Any,
    cluster_id: Any,
    workspace_id: Any | None = None,
    flavor: str | None = None,
) -> list[dict[str, Any]]:
    """ComputeQuota → ResourceQuota dict 列表.

    AWS 是 SoT; per-workspace 过滤时按 ComputeQuotaTarget.TeamName 匹配
    (workspace.name 即 TeamName).
    """
    del db, cluster_id
    summaries = await compute_quota.list_compute_quotas()
    quotas: list[dict[str, Any]] = []
    for s in summaries:
        team = (s.get("ComputeQuotaTarget") or {}).get("TeamName")
        if workspace_id is not None and team != str(workspace_id):
            continue
        try:
            detail = await compute_quota.describe_compute_quota(
                s.get("ComputeQuotaId") or ""
            )
        except Exception:
            detail = {}
        config = detail.get("ComputeQuotaConfig") or {}
        for r in config.get("ComputeQuotaResources") or []:
            flavor_key = (r.get("InstanceType") or "").replace("ml.", "")
            if flavor and flavor != flavor_key:
                continue
            quotas.append(
                {
                    "id": s.get("ComputeQuotaId"),
                    "workspace_id": team,
                    "flavor": flavor_key,
                    "gpu_type": None,
                    "gpu_quota": int(r.get("Count") or 0),
                    "gpu_used": 0,
                    "gpu_pending": 0,
                    "cpu_quota_millicores": 0,
                    "cpu_used_millicores": 0,
                    "memory_quota_mib": 0,
                    "memory_used_mib": 0,
                    "priority_class": "normal",
                    "preemption_policy": config.get("PreemptTeamTasks") or "Never",
                    "updated_at": s.get("LastModifiedTime"),
                }
            )
    return quotas


# =====================================================================
# 辅助
# =====================================================================

async def list_instance_groups(db: Any, cluster_id: Any) -> list[dict[str, Any]]:
    del db, cluster_id
    igs_aws = await cluster_describe.list_instance_groups()
    out: list[dict[str, Any]] = []
    for ig in igs_aws:
        out.append(
            {
                "id": ig.get("InstanceGroupName"),  # 用 group_name 当 id 简化
                "group_name": ig.get("InstanceGroupName"),
                "instance_type": ig.get("InstanceType"),
                "instance_count": int(ig.get("CurrentCount") or 0),
                "target_count": int(ig.get("TargetCount") or 0),
                "availability_zone": "us-west-2a",
            }
        )
    return out


async def count_nodes_by_health(db: Any, cluster_id: Any) -> dict[str, int]:
    del db, cluster_id
    rows = await nodes.list_cluster_nodes()
    out: dict[str, int] = {}
    for n in rows:
        st = n.get("InstanceStatus", {}).get("Status") or "Unknown"
        out[st] = out.get(st, 0) + 1
    return out


# =====================================================================
# 6) node_operation_log → audit_log (DDB)
# =====================================================================

async def log_node_operation(
    db: Any,
    cluster_id: Any,
    node_name: str,
    operation: str,
    actor_user_id: Any,
    actor_role: str,
    reason: str | None = None,
    aws_request_id: str | None = None,
    status: str = "submitted",
) -> dict[str, Any]:
    """RDS node_operation_log → DDB AuditLog (scope='cluster#<id>')."""
    del db
    from app.adapters.ddb import tables as _tables

    return await audit_repo.append(
        scope_key=_tables.scope_key_cluster(str(cluster_id)),
        actor_user_id=str(actor_user_id),
        actor_role=actor_role,
        operation=operation,
        target_type="node",
        target_id=node_name,
        status=status,
        reason=reason,
        aws_request_id=aws_request_id,
    )
