"""Cluster 模块 orchestration 层 · 业务流编排

职责:
- 调 adapters / AWS 客户端 + crud，把多步骤流程编排起来
- 公开导出给其他模块调用（summary / sync / node 操作）

导出（跨模块允许使用）:
- get_cluster_summary  (聚合 DB + AWS 活数据)
- sync_cluster         (AWS + K8s → DB 幂等 upsert)
- reboot_node / replace_node / delete_node (节点操作 · 管理员)
"""

from app.modules.cluster.orchestration.node_operations import (
    delete_node,
    reboot_node,
    replace_node,
)
from app.modules.cluster.orchestration.sync_from_aws import (
    describe_cluster_live,
    list_cluster_nodes_live,
)
from app.modules.cluster.orchestration.sync_from_k8s import (
    list_k8s_nodes,
)

__all__ = [
    "delete_node",
    "describe_cluster_live",
    "list_cluster_nodes_live",
    "list_k8s_nodes",
    "reboot_node",
    "replace_node",
]
