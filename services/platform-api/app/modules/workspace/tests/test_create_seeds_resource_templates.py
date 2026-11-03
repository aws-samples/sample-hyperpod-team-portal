"""建工作空间时按创建者请求语言预置资源模板; 预置失败不影响建 ws。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import i18n
from app.modules.workspace.api.schemas import WorkspaceCreate
from app.modules.workspace.orchestration import create as create_mod
from app.repositories import resource_templates as rt_repo


@pytest.fixture
def flow_env(monkeypatch):
    """把建 ws 流程里所有外部依赖 (AWS / K8s / DDB) 替换为 mock。"""
    monkeypatch.setattr(
        create_mod.cluster_crud, "get_cluster_by_id",
        AsyncMock(return_value={
            "id": "c1", "cluster_tag": "t", "hyperpod_cluster_arn": "arn:c1",
        }),
    )
    monkeypatch.setattr(create_mod.crud, "get_workspace_by_name", AsyncMock(return_value=None))
    monkeypatch.setattr(create_mod.crud, "get_workspace_by_namespace", AsyncMock(return_value=None))
    monkeypatch.setattr(create_mod, "_wait_namespace_ready", AsyncMock())
    monkeypatch.setattr(create_mod, "_seed_base_images", AsyncMock())
    monkeypatch.setattr(
        create_mod.ws_repo, "create_workspace", AsyncMock(return_value={"workspace_id": "ws-1"})
    )
    monkeypatch.setattr(create_mod.audit_repo, "append", AsyncMock())
    settings = MagicMock(platform_pod_role_arn="", eks_cluster_name="", kube_context="")
    monkeypatch.setattr(create_mod, "get_settings", lambda: settings)

    hp = MagicMock()
    hp.create_compute_quota = AsyncMock(
        return_value={"ComputeQuotaId": "q1", "ComputeQuotaArn": "arn:q1"}
    )
    k8s = MagicMock()
    k8s.create_workspace_service_account = AsyncMock()
    k8s.create_workspace_role_and_binding = AsyncMock()

    put = AsyncMock()
    monkeypatch.setattr(rt_repo, "list_all", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt_repo, "put", put)
    return hp, k8s, put


async def _create(hp, k8s):
    payload = WorkspaceCreate(cluster_id="arn:c1", name="team-a", display_name="Team A")
    return await create_mod.create_workspace_flow(
        None, payload, {"username": "admin", "user_id": "admin"}, hp, k8s
    )


@pytest.mark.parametrize(
    ("locale", "names"),
    [
        (i18n.EN_US, ["Small", "Medium", "Large", "Extra large"]),
        (i18n.ZH_CN, ["小规格", "中规格", "大规格", "超大规格"]),
    ],
)
async def test_create_seeds_templates_in_request_locale(flow_env, locale, names):
    hp, k8s, put = flow_env
    token = i18n.set_locale(locale)
    try:
        item = await _create(hp, k8s)
    finally:
        i18n.reset_locale(token)

    assert item["workspace_id"] == "ws-1"
    assert put.await_count == 4
    assert all(c.kwargs["workspace_id"] == "ws-1" for c in put.await_args_list)
    seeded = [c.kwargs["item_fields"]["name"] for c in put.await_args_list]
    assert seeded == names


async def test_seed_failure_does_not_fail_create(flow_env):
    hp, k8s, put = flow_env
    put.side_effect = RuntimeError("ddb down")

    item = await _create(hp, k8s)

    assert item["workspace_id"] == "ws-1"
    assert item["status"] == "active"
