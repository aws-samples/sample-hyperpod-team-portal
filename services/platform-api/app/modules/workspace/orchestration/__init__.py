"""Workspace 业务编排层.

三个文件:
- `create` · create_workspace_flow + add_member_flow
- `lifecycle` · update / delete / member role update / member remove
- `sync` · 从 AWS Team / K8s ns 拉元信息回填或一致性校验 (M1 占位)

orchestration 层是**唯一**允许:
- 调 persistence.crud 写 DB
- 调 adapters / HyperPodClient 调 AWS
- 抛 HTTPException

的地方。domain/* 必须是纯函数; response/* 只组装 view。
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
from app.modules.workspace.orchestration.sync import (
    sync_workspace_from_aws,
)

__all__ = [
    "add_member_flow",
    "create_workspace_flow",
    "delete_workspace_flow",
    "remove_member_flow",
    "sync_workspace_from_aws",
    "update_member_role_flow",
    "update_workspace_flow",
]
