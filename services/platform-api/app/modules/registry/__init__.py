"""Registry 模块 · 暴露 ECR / S3 资源选择只读端点 (训练/推理表单 dropdown 用)."""

from app.modules.registry.api.router import registry_router

__all__ = ["registry_router"]
