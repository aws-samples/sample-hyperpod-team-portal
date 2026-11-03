"""Backward-compat shim · 原 service.py 已拆分到 orchestration/ + response/.

拆分后:
- create_workspace_flow / add_member_flow   → orchestration/create.py
- update_workspace_flow / delete_workspace_flow
  / update_member_role_flow / remove_member_flow → orchestration/lifecycle.py
- build_workspace_detail / list_members_flow → response/builders.py

保留此文件是让现有 `from app.modules.workspace import service` 调用不破;
新代码请直接 import 子模块。
"""

from app.modules.workspace.orchestration.create import (
    add_member_flow,
    create_workspace_flow,
)
from app.modules.workspace.orchestration.lifecycle import (
    delete_workspace_flow,
    remove_member_flow,
    update_member_role_flow,
    update_workspace_flow,
)
from app.modules.workspace.response.builders import (
    build_workspace_detail,
    list_members_flow,
)

__all__ = [
    "add_member_flow",
    "build_workspace_detail",
    "create_workspace_flow",
    "delete_workspace_flow",
    "list_members_flow",
    "remove_member_flow",
    "update_member_role_flow",
    "update_workspace_flow",
]
