"""Training API 层 · FastAPI router + Pydantic schemas + deps."""

from __future__ import annotations

from app.modules.training.api.router import training_router

__all__ = ["training_router"]
