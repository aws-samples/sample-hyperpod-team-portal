"""Regression tests · 向后兼容 shim 没断.

全平台 5+ 处外部模块 (quota / quota_usage / training / logs / dev_instance
+ scripts / alembic) 仍通过旧路径 import workspace 子模块, 这些 shim 不能坏。
"""

from __future__ import annotations


def test_shim_crud_reexports_all_functions() -> None:
    # 旧代码: from app.modules.workspace import crud as ws_crud
    from app.modules.workspace import crud as ws_crud
    from app.modules.workspace.persistence import crud as real_crud

    # 公共 API 全量对齐
    expected = {
        "get_workspace",
        "get_workspace_by_name",
        "get_workspace_by_namespace",
        "list_workspaces",
        "create_workspace",
        "update_workspace",
        "delete_workspace",
        "count_members",
        "get_membership",
        "list_memberships",
        "add_membership",
        "update_membership_role",
        "delete_membership",
    }
    for fn_name in expected:
        assert hasattr(ws_crud, fn_name), f"shim 缺函数: {fn_name}"
        assert getattr(ws_crud, fn_name) is getattr(real_crud, fn_name), (
            f"shim 重导 {fn_name} 指向错"
        )


def test_shim_models_reexports_orm_classes() -> None:
    from app.modules.workspace import models as shim
    from app.modules.workspace.persistence.models import (
        UserWorkspaceRole,
        Workspace,
    )

    assert shim.Workspace is Workspace
    assert shim.UserWorkspaceRole is UserWorkspaceRole
    assert Workspace.__tablename__ == "workspace"
    assert UserWorkspaceRole.__tablename__ == "user_workspace_role"


def test_shim_service_reexports_flows() -> None:
    from app.modules.workspace import service
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

    assert service.create_workspace_flow is create_workspace_flow
    assert service.add_member_flow is add_member_flow
    assert service.update_workspace_flow is update_workspace_flow
    assert service.delete_workspace_flow is delete_workspace_flow
    assert service.update_member_role_flow is update_member_role_flow
    assert service.remove_member_flow is remove_member_flow
    assert service.build_workspace_detail is build_workspace_detail
    assert service.list_members_flow is list_members_flow


def test_shim_schemas_reexports_types() -> None:
    from app.modules.workspace import schemas
    from app.modules.workspace.api.schemas import (
        MemberAdd,
        MemberResponse,
        MemberUpdate,
        WorkspaceCreate,
        WorkspaceDetail,
        WorkspaceUpdate,
    )

    assert schemas.WorkspaceCreate is WorkspaceCreate
    assert schemas.WorkspaceDetail is WorkspaceDetail
    assert schemas.WorkspaceUpdate is WorkspaceUpdate
    assert schemas.MemberAdd is MemberAdd
    assert schemas.MemberUpdate is MemberUpdate
    assert schemas.MemberResponse is MemberResponse


def test_shim_router_module_exposes_workspace_router() -> None:
    from app.modules.workspace.api.router import workspace_router as real_router
    from app.modules.workspace.router import workspace_router as shim_router

    assert shim_router is real_router
