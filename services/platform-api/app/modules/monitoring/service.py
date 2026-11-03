"""Backward-compat shim · Prometheus HTTP 调用迁到 ``app.adapters.prometheus``.

旧代码可继续 ``from app.modules.monitoring.service import PromAPIError,
instant_query, range_query``.
新代码走 ``from app.adapters.prometheus import ...``.
"""

from __future__ import annotations

from app.adapters.prometheus import (
    PromAPIError,
    instant_query,
    range_query,
)

__all__ = ["PromAPIError", "instant_query", "range_query"]
