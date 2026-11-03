"""优先级管理模块 (WPC 档位 + 单任务优先级 + 抢占开关)."""
from __future__ import annotations

from app.modules.priority.api.router import priority_router

__all__ = ["priority_router"]
