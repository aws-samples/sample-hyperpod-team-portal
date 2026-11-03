"""Logs · 领域层 (纯函数, 无 IO).

- log_group_naming: HyperPod CloudWatch log group 命名规则
- insights_query: Logs Insights 查询串构造
- event_parsing: Fluent Bit JSON envelope → LogLine
"""

from app.modules.logs.domain.event_parsing import parse_insights_event  # noqa: F401
from app.modules.logs.domain.insights_query import build_training_job_query  # noqa: F401
from app.modules.logs.domain.log_group_naming import (  # noqa: F401
    build_log_group,
    cluster_id_suffix_from_arn,
    split_log_group,
)
