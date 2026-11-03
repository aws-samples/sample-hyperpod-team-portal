"""Backward-compat shim · 真实定义在 ``app.modules.monitoring.api.schemas``."""

from __future__ import annotations

from app.modules.monitoring.api.schemas import (
    InstantQueryPayload,
    PromResponse,
    QueryTemplate,
    RangeQueryPayload,
)

__all__ = [
    "InstantQueryPayload",
    "PromResponse",
    "QueryTemplate",
    "RangeQueryPayload",
]
