"""sync 404 分支 (CR 没了) 据 kueue_status 判别:
finished → 不做任何写; 非 finished (外部删) → mark_stopped。"""
from unittest.mock import AsyncMock

import pytest

from app.modules.inference.orchestration import sync as sync_mod
from app.services.k8s_client import K8sAPIError


def _k8s_404():
    k8s = AsyncMock()
    k8s.get_inference_endpoint.side_effect = K8sAPIError(code="404", message="not found")
    return k8s


@pytest.mark.asyncio
async def test_404_finished_does_nothing(monkeypatch):
    upd = AsyncMock()
    ms = AsyncMock()
    monkeypatch.setattr(sync_mod.crud, "update", upd)
    monkeypatch.setattr(sync_mod.crud, "mark_stopped", ms)
    row = {"id": "i1", "workspace_id": "ws-1", "k8s_namespace": "ns",
           "k8s_endpoint_name": "ep", "kueue_status": "finished"}
    out, conds, pods, workloads = await sync_mod.sync_from_k8s(None, _k8s_404(), row)
    upd.assert_not_awaited()
    ms.assert_not_awaited()
    assert (out, conds, pods, workloads) == (row, [], [], [])


@pytest.mark.asyncio
async def test_404_active_calls_mark_stopped(monkeypatch):
    upd = AsyncMock()
    ms = AsyncMock(return_value={"id": "i1"})
    monkeypatch.setattr(sync_mod.crud, "update", upd)
    monkeypatch.setattr(sync_mod.crud, "mark_stopped", ms)
    row = {"id": "i1", "workspace_id": "ws-1", "k8s_namespace": "ns",
           "k8s_endpoint_name": "ep", "kueue_status": "started"}
    await sync_mod.sync_from_k8s(None, _k8s_404(), row)
    ms.assert_awaited_once()
    upd.assert_not_awaited()
