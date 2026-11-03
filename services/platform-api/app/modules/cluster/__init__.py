"""Cluster 模块 · 资产导向分层

分层:
- domain/        纯函数规则（health_check / capacity）
- orchestration/ 业务流编排（sync / summary / node ops）
- persistence/   models + crud
- api/           router + schemas + deps
- response/      ORM → dict 视图构建
- tests/         单测

对外公共接口（跨模块允许 import）:
- `crud`           —— persistence.crud 的门面 re-export（兼容旧调用方）
- `cluster_router` —— FastAPI 路由
- `orchestration`  —— 业务流编排入口

跨模块 import 规范:
- workspace/logs/quota 模块通过 `from app.modules.cluster import crud as cluster_crud`
  只调 `get_cluster_by_id` / `get_cluster_by_tag` / `list_clusters` / `list_instance_groups` 等
- 绝不直接 import `persistence.models.*` 或 `api.*` 内部符号
"""

from app.modules.cluster.api.router import cluster_router
from app.modules.cluster.persistence import crud

__all__ = [
    "cluster_router",
    "crud",
]
