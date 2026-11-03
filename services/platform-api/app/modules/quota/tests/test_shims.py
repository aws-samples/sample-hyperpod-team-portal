"""验证老 import path 经 shim 仍能工作 (backward compat)."""

from __future__ import annotations


def test_old_quota_router_shim() -> None:
    from app.modules.quota.api.router import quota_router as new
    from app.modules.quota.router import quota_router

    assert quota_router is new, "shim 必须 re-export 同一 router 实例"


def test_old_quota_schemas_shim() -> None:
    from app.modules.quota import schemas as old
    from app.modules.quota.api import schemas as new

    # 关键类型应是同一 Python 对象 (re-export 不克隆)
    assert old.ComputeQuota is new.ComputeQuota
    assert old.QuotaUsage is new.QuotaUsage
    assert old.CreateComputeQuotaPayload is new.CreateComputeQuotaPayload


def test_old_quota_service_shim_exposes_orchestration() -> None:
    from app.modules.quota import service as old
    from app.modules.quota.orchestration.allocate import create_workspace_quota
    from app.modules.quota.orchestration.workspace_quota import get_workspace_quota

    assert old.create_workspace_quota is create_workspace_quota
    assert old.get_workspace_quota is get_workspace_quota


def test_public_reexports() -> None:
    """app.modules.quota 顶层必须公开 orchestration 函数."""
    from app.modules.quota import (
        create_workspace_quota,
        delete_workspace_quota,
        fetch_quota_usage,
        get_workspace_quota,
        list_cluster_quotas,
        update_workspace_quota,
    )

    for fn in (
        create_workspace_quota,
        delete_workspace_quota,
        fetch_quota_usage,
        get_workspace_quota,
        list_cluster_quotas,
        update_workspace_quota,
    ):
        assert callable(fn)
