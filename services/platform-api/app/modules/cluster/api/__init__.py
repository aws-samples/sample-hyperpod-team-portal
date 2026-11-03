"""Cluster 模块 HTTP API 层

对外只暴露 `cluster_router`，其余 deps/schemas 仅在 api/ 内使用。
"""

from app.modules.cluster.api.router import cluster_router

__all__ = ["cluster_router"]
