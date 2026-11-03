"""Cluster 模块领域层 · 纯函数，无 IO

暴露:
- health_check: 节点健康状态融合规则（SageMaker label + K8s Ready）
- capacity: 容量聚合算法（GPU 百分比、flavor key 映射、sync_status 推导）
"""

from app.modules.cluster.domain import capacity as capacity
from app.modules.cluster.domain import health_check as health_check
