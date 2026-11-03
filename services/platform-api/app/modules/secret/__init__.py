"""Secret 模块 · 每人托管自己的 GitHub token 到 k8s Secret."""

from app.modules.secret.api.router import secret_router

__all__ = ["secret_router"]
