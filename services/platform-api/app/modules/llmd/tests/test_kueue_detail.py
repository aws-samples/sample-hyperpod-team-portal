"""llmd kueue-detail 端点: 按 workload 名实时查 conditions; 找不到返空。"""
from unittest.mock import AsyncMock

import pytest

from app.modules.llmd.api import router as llmd_router_mod


@pytest.mark.asyncio
async def test_kueue_detail_returns_conditions(monkeypatch):
    row = {"id": "id1", "workspace_id": "ws1", "k8s_namespace": "ns1"}
    monkeypatch.setattr(llmd_router_mod.crud, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(llmd_router_mod, "assert_ws_member", AsyncMock())
    k8s = AsyncMock()
    k8s.list_workloads = AsyncMock(return_value=[
        {"metadata": {"name": "leaderworkerset-t-multi-0-abc"},
         "status": {"conditions": [{"type": "QuotaReserved", "status": "False"}],
                    "admission": {"clusterQueue": "cq"}}},
        {"metadata": {"name": "other-wl"}, "status": {"conditions": []}},
    ])
    out = await llmd_router_mod.get_llmd_kueue_detail(
        id="id1", workload="leaderworkerset-t-multi-0-abc", k8s=k8s,
        current_user={"sub": "u"},
    )
    assert out["conditions"][0]["type"] == "QuotaReserved"
    assert out["admission"]["clusterQueue"] == "cq"


@pytest.mark.asyncio
async def test_kueue_detail_workload_not_found_empty(monkeypatch):
    row = {"id": "id1", "workspace_id": "ws1", "k8s_namespace": "ns1"}
    monkeypatch.setattr(llmd_router_mod.crud, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(llmd_router_mod, "assert_ws_member", AsyncMock())
    k8s = AsyncMock()
    k8s.list_workloads = AsyncMock(return_value=[])
    out = await llmd_router_mod.get_llmd_kueue_detail(
        id="id1", workload="missing", k8s=k8s, current_user={"sub": "u"},
    )
    assert out == {"conditions": [], "admission": {}}
