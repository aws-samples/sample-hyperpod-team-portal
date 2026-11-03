"""集群类型 (DDB-only).

历史: 这里曾是 SQLAlchemy ORM (Cluster / InstanceGroup / NodeStatus /
ResourceQuota / NodeOperationLog). 切到 DDB + AWS-as-SoT 后:

- Cluster        ← AWS DescribeCluster (cluster_describe.get_cluster_summary)
- InstanceGroup  ← AWS DescribeCluster.InstanceGroups
- NodeStatus     ← AWS ListClusterNodes + K8s Node
- ResourceQuota  ← AWS DescribeComputeQuota
- NodeOperationLog ← DDB AuditLog (scope_key='cluster#<id>')

全部退化为 dict type alias. 业务字段映射 helper 见
``app/adapters/aws/cluster_describe.py``.
"""

from __future__ import annotations

from typing import Any

# DDB / AWS items 一律 plain dict
Cluster = dict[str, Any]
InstanceGroup = dict[str, Any]
NodeStatus = dict[str, Any]
ResourceQuota = dict[str, Any]
NodeOperationLog = dict[str, Any]

__all__ = [
    "Cluster",
    "InstanceGroup",
    "NodeOperationLog",
    "NodeStatus",
    "ResourceQuota",
]
