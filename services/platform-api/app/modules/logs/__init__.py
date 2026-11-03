"""Logs 模块 · CloudWatch Logs Insights 日志拉取.

资产导向布局 (Wave 2):
    - domain/       log group 命名 + event 解析 + query 构造 (纯)
    - orchestration/ fetch_training_logs 业务流 (组装 cluster/ws ctx + 调 adapter)
    - api/          router + schemas
    - persistence/  (空 · 无表, 所有状态在 CW Logs)
    - response/     (视图构建, 当前 router 直接返)

向后兼容 shim:
    旧 import path 仍有效 ::

        from app.modules.logs import service
        from app.modules.logs.service import LogsServiceError
        from app.modules.logs.schemas import LogLine, LogResponse

    推荐新代码 ::

        from app.modules.logs.orchestration import fetch_training_logs
        from app.modules.logs.api.schemas import LogResponse
        from app.adapters.aws.cloudwatch_logs import run_insights_query
"""
