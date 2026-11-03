"""Backward-compat shim · 真实 router 在 ``app.modules.logs.api.router``."""

from __future__ import annotations

from app.modules.logs.api.router import logs_router

__all__ = ["logs_router"]
