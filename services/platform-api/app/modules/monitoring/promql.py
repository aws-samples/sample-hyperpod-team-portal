"""Backward-compat shim · 真实 promql 在 ``app.modules.monitoring.domain.promql``."""

from __future__ import annotations

from app.modules.monitoring.domain.promql import (
    DEV_INSTANCE_KPI_TEMPLATES,
    DEV_INSTANCE_TEMPLATES,
    TRAINING_TEMPLATES,
)

__all__ = [
    "DEV_INSTANCE_KPI_TEMPLATES",
    "DEV_INSTANCE_TEMPLATES",
    "TRAINING_TEMPLATES",
]
