"""Backward-compat shim · 原 schemas.py 已搬到 api/schemas.py."""

from app.modules.workspace.api.schemas import (
    MemberAdd,
    MemberResponse,
    MemberUpdate,
    QuotaResourceRequest,
    WorkspaceCreate,
    WorkspaceDetail,
    WorkspaceSummary,
    WorkspaceUpdate,
)

__all__ = [
    "MemberAdd",
    "MemberResponse",
    "MemberUpdate",
    "QuotaResourceRequest",
    "WorkspaceCreate",
    "WorkspaceDetail",
    "WorkspaceSummary",
    "WorkspaceUpdate",
]
