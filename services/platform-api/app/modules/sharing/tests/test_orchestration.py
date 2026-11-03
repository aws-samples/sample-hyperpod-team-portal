import app.main  # noqa: F401
import pytest
from fastapi import HTTPException


def _user(name):
    return {"user_id": name, "username": name}


async def _patch_common(monkeypatch, *, res_creator="owner", members=("owner", "alice")):
    from app.modules.sharing import orchestration as orch

    async def fake_get_resource(ws, rt, rid):
        # train/dev 都映射到 resource_index; 返回带 creator 的行, deleted_at 缺失
        return {"creator_user_id": res_creator, "resource_id": rid}

    async def fake_get_membership(db, ws, username):
        return {"username": username} if username in members else None

    monkeypatch.setattr(orch.ri_repo, "get_resource", fake_get_resource)
    monkeypatch.setattr(orch.ws_crud, "get_membership", fake_get_membership)
    return orch


async def test_share_by_creator_to_member_ok(monkeypatch):
    orch = await _patch_common(monkeypatch)
    granted = []

    async def fake_grant(**kw):
        granted.append(kw["target_username"])
        return {"target_username": kw["target_username"]}

    monkeypatch.setattr(orch.shares_repo, "grant", fake_grant)

    out = await orch.share_resource("ws1", "dev", "d1", ["alice"], _user("owner"))
    assert granted == ["alice"]
    assert len(out) == 1


async def test_share_to_self_bad_request(monkeypatch):
    # owner 是 creator, 分享给自己 → 400 (不校验成员就先挡)
    orch = await _patch_common(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        await orch.share_resource("ws1", "dev", "d1", ["owner"], _user("owner"))
    assert ei.value.status_code == 400


async def test_share_by_non_creator_forbidden(monkeypatch):
    orch = await _patch_common(monkeypatch, res_creator="owner")
    with pytest.raises(HTTPException) as ei:
        await orch.share_resource("ws1", "dev", "d1", ["alice"], _user("mallory"))
    assert ei.value.status_code == 403


async def test_share_to_non_member_bad_request(monkeypatch):
    orch = await _patch_common(monkeypatch, members=("owner",))
    with pytest.raises(HTTPException) as ei:
        await orch.share_resource("ws1", "dev", "d1", ["stranger"], _user("owner"))
    assert ei.value.status_code == 400


async def test_share_missing_resource_404(monkeypatch):
    orch = await _patch_common(monkeypatch)

    async def none_res(ws, rt, rid):
        return None

    monkeypatch.setattr(orch.ri_repo, "get_resource", none_res)
    with pytest.raises(HTTPException) as ei:
        await orch.share_resource("ws1", "dev", "d1", ["alice"], _user("owner"))
    assert ei.value.status_code == 404


async def test_share_invalid_res_type_400(monkeypatch):
    orch = await _patch_common(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        await orch.share_resource("ws1", "inference", "i1", ["alice"], _user("owner"))
    assert ei.value.status_code == 400


async def test_share_deleted_resource_404(monkeypatch):
    orch = await _patch_common(monkeypatch)

    async def deleted_res(ws, rt, rid):
        return {"creator_user_id": "owner", "resource_id": rid, "deleted_at": "2026-01-01T00:00:00Z"}

    monkeypatch.setattr(orch.ri_repo, "get_resource", deleted_res)
    with pytest.raises(HTTPException) as ei:
        await orch.share_resource("ws1", "dev", "d1", ["alice"], _user("owner"))
    assert ei.value.status_code == 404
