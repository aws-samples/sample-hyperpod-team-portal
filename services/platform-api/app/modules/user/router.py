"""Backward-compat shim · 真实 router 在 ``app.modules.user.api.router``."""

from __future__ import annotations

from app.modules.user.api.router import user_router

__all__ = ["user_router"]
