"""HTTP 响应 dict 构建器 (DDB-only / dict-based).

历史: ORM (ResourceQuota / Cluster) → JSON. 现在输入是 dict (来自
``crud.list_resource_quotas`` / ``crud.get_cluster_by_tag``).
"""

from __future__ import annotations

from typing import Any

from app.modules.cluster.domain.capacity import quota_usage_pct


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def build_quota_flat(q: dict[str, Any]) -> dict[str, Any]:
    """单条 ResourceQuota dict → flat dict (平铺列表行格式)."""
    gpu_quota = int(q.get("gpu_quota") or 0)
    gpu_used = int(q.get("gpu_used") or 0)
    return {
        "id": str(q.get("id")) if q.get("id") else None,
        "workspace_id": str(q.get("workspace_id")) if q.get("workspace_id") else None,
        "flavor": q.get("flavor"),
        "gpu_type": q.get("gpu_type"),
        "gpu": {
            "quota": gpu_quota,
            "used": gpu_used,
            "pending": int(q.get("gpu_pending") or 0),
            "usage_pct": quota_usage_pct(gpu_used, gpu_quota),
        },
        "cpu_millicores": {
            "quota": int(q.get("cpu_quota_millicores") or 0),
            "used": int(q.get("cpu_used_millicores") or 0),
        },
        "memory_mib": {
            "quota": int(q.get("memory_quota_mib") or 0),
            "used": int(q.get("memory_used_mib") or 0),
        },
        "priority_class": q.get("priority_class"),
        "preemption_policy": q.get("preemption_policy"),
        "updated_at": _iso(q.get("updated_at")),
    }


def build_quotas_flat_list(quotas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """多条 ResourceQuota → 平铺视图."""
    return [build_quota_flat(q) for q in quotas]


def build_quota_flavor_node(q: dict[str, Any], ws_key: str) -> dict[str, Any]:
    """tree 叶节点 (flavor 层级)."""
    gpu_quota = int(q.get("gpu_quota") or 0)
    gpu_used = int(q.get("gpu_used") or 0)
    flavor = q.get("flavor") or "unknown"
    return {
        "id": f"ws-{ws_key}-{flavor}",
        "flavor": flavor,
        "level": "flavor",
        "gpu_type": q.get("gpu_type"),
        "gpu": {
            "quota": gpu_quota,
            "used": gpu_used,
            "pending": int(q.get("gpu_pending") or 0),
            "usage_pct": quota_usage_pct(gpu_used, gpu_quota),
        },
        "cpu_millicores": {
            "quota": int(q.get("cpu_quota_millicores") or 0),
            "used": int(q.get("cpu_used_millicores") or 0),
        },
        "memory_mib": {
            "quota": int(q.get("memory_quota_mib") or 0),
            "used": int(q.get("memory_used_mib") or 0),
        },
        "priority_class": q.get("priority_class"),
        "preemption_policy": q.get("preemption_policy"),
    }


def build_quotas_tree(
    cluster_id: Any, quotas: list[dict[str, Any]]
) -> dict[str, Any]:
    """树状视图: cluster → workspace → flavor 嵌套."""
    ws_buckets: dict[str, list[dict[str, Any]]] = {}
    for q in quotas:
        wid = q.get("workspace_id")
        key = str(wid) if wid else "shared"
        ws_buckets.setdefault(key, []).append(q)

    workspace_children: list[dict[str, Any]] = []
    for ws_key, ws_quotas in ws_buckets.items():
        flavor_nodes = [build_quota_flavor_node(q, ws_key) for q in ws_quotas]
        workspace_children.append(
            {
                "id": f"ws-{ws_key}",
                "name": ws_key,
                "level": "workspace",
                "children": flavor_nodes,
            }
        )

    return {
        "view": "tree",
        "cluster_id": str(cluster_id),
        "tree": [
            {
                "id": "cluster-root",
                "name": "Cluster Pool",
                "level": "cluster",
                "children": workspace_children,
            }
        ],
    }


def build_cluster_info(cluster: dict[str, Any]) -> dict[str, Any]:
    """Cluster dict → 顶层元数据 dict."""
    return {
        "id": str(cluster.get("id")) if cluster.get("id") else None,
        "cluster_tag": cluster.get("cluster_tag"),
        "type": cluster.get("type"),
        "region": cluster.get("region"),
        "state": cluster.get("state"),
        "workspace_scope": cluster.get("workspace_scope") or "shared",
        "eks_cluster_name": cluster.get("eks_cluster_name"),
        "hyperpod_cluster_arn": cluster.get("hyperpod_cluster_arn"),
        "last_synced_at": _iso(cluster.get("last_synced_at")),
        "created_at": _iso(cluster.get("created_at")),
    }
