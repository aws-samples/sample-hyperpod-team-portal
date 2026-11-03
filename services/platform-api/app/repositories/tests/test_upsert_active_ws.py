"""upsert_resource 接受 active_ws 顶层属性; create_stub 据 kueue_status 传入。"""
from unittest.mock import AsyncMock

import pytest

from app.repositories import resource_index as ri


@pytest.mark.asyncio
async def test_upsert_sets_active_ws_top_level(monkeypatch):
    captured = {}

    async def fake_put(table, item, *, ensure_new=False):
        captured["item"] = item

    monkeypatch.setattr(ri.base, "put_item", fake_put)
    monkeypatch.setattr(ri, "get_resource", AsyncMock(return_value=None))
    await ri.upsert_resource(
        workspace_id="ws-1", resource_type="dev", resource_id="d1",
        creator_user_id="alice", k8s_namespace="ns", k8s_name="n",
        resource_kind="Workspace", display_name="d", metadata={"phase": "x"},
        active_ws="ws-1",
    )
    assert captured["item"]["active_ws"] == "ws-1"


@pytest.mark.asyncio
async def test_upsert_omits_active_ws_when_none(monkeypatch):
    captured = {}

    async def fake_put(table, item, *, ensure_new=False):
        captured["item"] = item

    monkeypatch.setattr(ri.base, "put_item", fake_put)
    monkeypatch.setattr(ri, "get_resource", AsyncMock(return_value=None))
    await ri.upsert_resource(
        workspace_id="ws-1", resource_type="dev", resource_id="d1",
        creator_user_id="alice", k8s_namespace="ns", k8s_name="n",
        resource_kind="Workspace", display_name="d", metadata={"phase": "x"},
        active_ws=None,
    )
    assert "active_ws" not in captured["item"]


@pytest.mark.asyncio
async def test_create_stub_active_ws_from_kueue_status(monkeypatch):
    captured = {}

    async def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(ri, "upsert_resource", fake_upsert)
    await ri.create_stub(
        workspace_id="ws-1", resource_type="dev", resource_id="d1",
        resource_version=1, creator_user_id="alice", k8s_namespace="ns",
        k8s_name="n", resource_kind="Workspace", display_name="d",
        md={"phase": "Running", "kueue_status": "started"},
    )
    assert captured["active_ws"] == "ws-1"
