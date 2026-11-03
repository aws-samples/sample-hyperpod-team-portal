"""Backward-compat shim · re-export from app.modules.quota.orchestration + response.

Wave 2 重构 (2026-05-12) 把 service 拆到 orchestration/ + response/ 两层.
保留此文件让旧 `from app.modules.quota import service; service.get_workspace_quota(...)`
调用继续生效.
"""

from app.modules.quota.orchestration.allocate import (
    create_workspace_quota,
    delete_workspace_quota,
    update_workspace_quota,
)
from app.modules.quota.orchestration.workspace_quota import (
    get_workspace_quota,
    list_cluster_quotas,
)
from app.modules.quota.response.builders import (
    aws_borrow_limit_to_schema,
    aws_quota_to_schema,
    aws_resource_to_schema,
    aws_sharing_to_schema,
    aws_target_to_schema,
)

__all__ = [
    "aws_borrow_limit_to_schema",
    "aws_quota_to_schema",
    "aws_resource_to_schema",
    "aws_sharing_to_schema",
    "aws_target_to_schema",
    "create_workspace_quota",
    "delete_workspace_quota",
    "get_workspace_quota",
    "list_cluster_quotas",
    "update_workspace_quota",
]
