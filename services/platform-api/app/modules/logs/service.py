"""Backward-compat shim · logs 业务流迁到 ``orchestration``, AWS 调用迁到 ``adapters``.

旧 import (保持可用) ::

    from app.modules.logs.service import (
        LogsServiceError,
        fetch_training_logs,
        build_log_group,
    )

新代码 ::

    from app.modules.logs.orchestration import (
        LogsServiceError, fetch_training_logs,
    )
    from app.modules.logs.domain import build_log_group
"""

from __future__ import annotations

from app.modules.logs.domain.log_group_naming import build_log_group
from app.modules.logs.orchestration import (
    LogsServiceError,
    fetch_training_logs,
)

__all__ = [
    "LogsServiceError",
    "build_log_group",
    "fetch_training_logs",
]
