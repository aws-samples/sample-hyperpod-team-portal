"""Backward-compat shim · 原 router.py 已搬到 api/router.py.

保留此 shim 让 `from app.modules.workspace.router import workspace_router`
(app/api/v1/router.py 在用) 继续可用。
"""

from app.modules.workspace.api.router import workspace_router

__all__ = ["workspace_router"]
