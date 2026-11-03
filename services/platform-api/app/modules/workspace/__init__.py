"""Workspace 模块 (资产导向结构 · 2026-05-12 Wave 2 B3 重构).

目录分层:
    domain/          纯函数 · AWS Team 映射 · namespace 规范
    orchestration/   业务编排 · create / lifecycle / sync
    persistence/     ORM models + CRUD (允许全局直读 workspace 表, 例外 #1)
    api/             router + schemas + deps
    response/        detail/list 视图构建

对外稳定入口:
    from app.modules.workspace import crud as ws_crud   # 兼容 shim
    from app.modules.workspace.models import Workspace  # 兼容 shim
    from app.modules.workspace.router import workspace_router
"""
