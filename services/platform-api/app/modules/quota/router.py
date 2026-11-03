"""Backward-compat shim · re-export from app.modules.quota.api.router.

Wave 2 重构 (2026-05-12) 把 router 搬到 api/router.py, 这里保留旧 import path
避免 `app.api.v1.router` 等调用方断链.
"""

from app.modules.quota.api.router import quota_router

__all__ = ["quota_router"]
