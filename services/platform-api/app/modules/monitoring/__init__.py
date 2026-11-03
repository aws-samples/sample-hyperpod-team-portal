"""Monitoring 模块 · Prometheus / AMP 指标查询与模板.

资产导向布局 (Wave 2):
    - domain/       PromQL 模板 + 节点 regex / 变量替换
    - orchestration/ 业务流 (取 job/devinstance ctx → 渲染模板)
    - api/          router + schemas
    - persistence/  (空 · 无独占表)
    - response/     (视图构建, 当前直接返 pydantic)

向后兼容 shim:
    旧 import path 仍有效 ::

        from app.modules.monitoring import promql, service
        from app.modules.monitoring.schemas import QueryTemplate
        from app.modules.monitoring.service import PromAPIError

    推荐新代码走新路径::

        from app.modules.monitoring.domain import promql
        from app.modules.monitoring.api.schemas import QueryTemplate
        from app.adapters.prometheus import PromAPIError, instant_query, range_query
"""
