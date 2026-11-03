"""Backward-compat shim · 真实定义在 ``app.modules.logs.api.schemas``."""

from __future__ import annotations

from app.modules.logs.api.schemas import LogLine, LogResponse

__all__ = ["LogLine", "LogResponse"]
