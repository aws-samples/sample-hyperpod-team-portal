"""Backward-compat shim · 原 crud.py 已搬到 persistence/crud.py.

保留此文件是因为全平台 5+ 处调用方式:
    from app.modules.workspace import crud as ws_crud
    await ws_crud.get_workspace(db, ws_id)
    await ws_crud.list_workspaces(...)

这些签名在 Wave 2 之后必须保持稳定。新代码推荐:
    from app.modules.workspace.persistence import crud as ws_crud
"""

from app.modules.workspace.persistence.crud import (
    add_membership,
    count_members,
    create_workspace,
    delete_membership,
    delete_workspace,
    get_membership,
    get_workspace,
    get_workspace_by_name,
    get_workspace_by_namespace,
    list_memberships,
    list_workspaces,
    update_membership_role,
    update_workspace,
)

__all__ = [
    "add_membership",
    "count_members",
    "create_workspace",
    "delete_membership",
    "delete_workspace",
    "get_membership",
    "get_workspace",
    "get_workspace_by_name",
    "get_workspace_by_namespace",
    "list_memberships",
    "list_workspaces",
    "update_membership_role",
    "update_workspace",
]
