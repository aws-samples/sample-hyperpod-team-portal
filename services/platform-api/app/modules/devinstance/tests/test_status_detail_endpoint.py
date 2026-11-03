"""开发机 status-detail 端点: assert_ws_member 鉴权 + 只返 status_detail。"""
import pytest
from fastapi import HTTPException

import importlib

# devinstance api/__init__.py 把 APIRouter 实例绑成了 `router` 名, 故 `import ...api.router`
# 会拿到 APIRouter 而非模块; 用 import_module 明确取 router.py 模块对象。
r = importlib.import_module("app.modules.devinstance.api.router")


@pytest.mark.asyncio
async def test_status_detail_returns_field(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "d1", "workspace_id": "ws-1",
                "status_detail": [{"type": "Available"}]}

    async def fake_assert(ws_id, user):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_dev_instance_status_detail("d1", current_user={"id": "u"})
    assert out == {"status_detail": [{"type": "Available"}]}


@pytest.mark.asyncio
async def test_status_detail_404(monkeypatch):
    async def fake_get(db, id_):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    with pytest.raises(HTTPException) as exc:
        await r.get_dev_instance_status_detail(
            "missing", current_user={"id": "u"}
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_detail_forbidden_non_member(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "d1", "workspace_id": "ws-1", "status_detail": []}

    async def fake_assert(ws_id, user):
        raise HTTPException(403, "not a member")

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    with pytest.raises(HTTPException) as exc:
        await r.get_dev_instance_status_detail("d1", current_user={"id": "u"})
    assert exc.value.status_code == 403
