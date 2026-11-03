"""训练 status-detail 端点: assert_ws_member 鉴权 + 只返 status_detail。"""
import pytest
from fastapi import HTTPException

from app.modules.training.api import router as r


@pytest.mark.asyncio
async def test_status_detail_returns_field(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "t1", "workspace_id": "ws-1",
                "status_detail": {"conditions": [{"type": "Running"}]}}

    async def fake_assert(ws_id, user):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_training_status_detail("t1", current_user={"id": "u"})
    assert out == {"status_detail": {"conditions": [{"type": "Running"}]}}


@pytest.mark.asyncio
async def test_status_detail_404(monkeypatch):
    async def fake_get(db, id_):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    with pytest.raises(HTTPException) as exc:
        await r.get_training_status_detail("missing", current_user={"id": "u"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_detail_forbidden_non_member(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "t1", "workspace_id": "ws-1", "status_detail": {}}

    async def fake_assert(ws_id, user):
        raise HTTPException(403, "not a member")

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    with pytest.raises(HTTPException) as exc:
        await r.get_training_status_detail("t1", current_user={"id": "u"})
    assert exc.value.status_code == 403
