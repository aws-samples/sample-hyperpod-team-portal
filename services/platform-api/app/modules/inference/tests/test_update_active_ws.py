"""inference crud.update 改部分更新: 只写 endpoint_url/alb_dns/last_sync_at,
不再整行 put, 不碰 active_ws/kueue_status (那些归 informer)。"""
import pytest

from app.modules.inference.persistence import crud


@pytest.mark.asyncio
async def test_update_writes_only_business_fields(monkeypatch):
    captured = {}

    async def fake_ubf(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(crud.ri_repo, "update_business_fields", fake_ubf)
    row = {
        "workspace_id": "ws-1", "id": "i1",
        "endpoint_url": "https://ep", "alb_dns": "alb-123.elb",
        "kueue_status": "started",
        "phase": "DeploymentComplete",
    }
    await crud.update(None, row)

    fields = captured["fields"]
    assert fields["endpoint_url"] == "https://ep"
    assert fields["alb_dns"] == "alb-123.elb"
    assert "last_sync_at" in fields
    assert "kueue_status" not in fields
    assert "phase" not in fields
    assert "active_ws" not in fields


@pytest.mark.asyncio
async def test_update_does_not_call_upsert(monkeypatch):
    called = {"upsert": False}

    async def fake_ubf(**kwargs):
        pass

    async def fake_upsert(**kwargs):
        called["upsert"] = True
        return {}

    monkeypatch.setattr(crud.ri_repo, "update_business_fields", fake_ubf)
    monkeypatch.setattr(crud.ri_repo, "upsert_resource", fake_upsert)
    await crud.update(None, {"workspace_id": "ws-1", "id": "i1"})
    assert called["upsert"] is False
