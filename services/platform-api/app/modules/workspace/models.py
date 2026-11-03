"""Backward-compat shim · 原 models.py 已搬到 persistence/models.py.

保留此文件是因为:
1. alembic/env.py 仍 `import app.modules.workspace.models as _workspace_models`
2. scripts/seed_* / 外部模块 (quota.service) 仍 `from app.modules.workspace.models import Workspace`

请勿在新代码里 import 本文件, 改走 `app.modules.workspace.persistence.models`。
"""

from app.modules.workspace.persistence.models import UserWorkspaceRole, Workspace

__all__ = ["UserWorkspaceRole", "Workspace"]
