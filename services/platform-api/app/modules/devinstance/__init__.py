"""devinstance · 开发机模块 (Workspace CRD 包装).

资产导向五层:
    domain/        纯 CR 渲染 + 字段约束 (无 IO)
    orchestration/ 业务流编排 (调 adapters + persistence + domain)
    persistence/   ORM model + CRUD (表: dev_instance)
    response/      ORM row → Pydantic DTO (拉 workspace / user display_name)
    api/           HTTP 路由 + Pydantic 入参 + deps

对外稳定入口 (按需 import 避免 pytest 多路径收集触发 SQLAlchemy 重复
table 注册, 所以本 __init__ 不做 eager 加载, 只提供 ``__getattr__`` 懒绑):

    from app.modules.devinstance.api.router import router as devinstance_router
    from app.modules.devinstance.persistence.models import DevInstance
    from app.modules.devinstance.api.schemas import DevInstanceCreate
    from app.modules.devinstance.orchestration import create_dev_instance_flow
    from app.modules.devinstance.domain.cr import render_workspace_cr

禁止跨模块 import 子层内部实现 (除了上面列的稳定入口).
"""

from __future__ import annotations

# 懒绑符号 → 模块 · 命中时才 import, 不在 `import app.modules.devinstance` 时执行
_LAZY_SYMBOLS: dict[str, tuple[str, str]] = {
    # attr_name: (module_path, attr_in_module)
    "DevInstance": ("app.modules.devinstance.persistence.models", "DevInstance"),
    "router": ("app.modules.devinstance.api.router", "router"),
    "AccessInfo": ("app.modules.devinstance.api.schemas", "AccessInfo"),
    "DevInstanceCreate": ("app.modules.devinstance.api.schemas", "DevInstanceCreate"),
    "DevInstanceDetail": ("app.modules.devinstance.api.schemas", "DevInstanceDetail"),
    "DevInstanceListItem": ("app.modules.devinstance.api.schemas", "DevInstanceListItem"),
    "DevInstanceUpdate": ("app.modules.devinstance.api.schemas", "DevInstanceUpdate"),
    "SharedPVCInfo": ("app.modules.devinstance.api.schemas", "SharedPVCInfo"),
    "TemplateCreate": ("app.modules.devinstance.api.schemas", "TemplateCreate"),
    "TemplateInfo": ("app.modules.devinstance.api.schemas", "TemplateInfo"),
    "TemplatePatchAllowedImages": (
        "app.modules.devinstance.api.schemas",
        "TemplatePatchAllowedImages",
    ),
    "VolumeMount": ("app.modules.devinstance.api.schemas", "VolumeMount"),
}


def __getattr__(name: str):
    """PEP 562 lazy attribute access · 按需加载."""
    if name in _LAZY_SYMBOLS:
        import importlib

        module_path, attr = _LAZY_SYMBOLS[name]
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted(_LAZY_SYMBOLS.keys())
