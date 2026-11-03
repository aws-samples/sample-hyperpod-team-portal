"""Backward-compat shim · 真实 router 在 ``app.modules.monitoring.api.router``."""

from __future__ import annotations

from app.modules.monitoring.api.router import monitoring_router

__all__ = ["monitoring_router"]
