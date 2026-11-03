"""资源模板模块 (开发机/训练/推理 公用一表)."""
from __future__ import annotations

from app.modules.resource_templates.api.router import resource_templates_router
from app.modules.resource_templates.orchestration.service import ensure_seeded

# ensure_seeded: 幂等预置默认模板 (名称/描述按当前请求语言生成)。
# 建工作空间时由 workspace 模块调用; list 端点仍保留懒加载兜底 (老 ws)。
__all__ = ["ensure_seeded", "resource_templates_router"]
