import app.main  # noqa: F401


async def test_list_by_workspace_includes_shared(monkeypatch):
    from app.modules.devinstance.persistence import crud
    from app.modules.sharing import visibility

    # ResourceIndex 返 3 行: d1(我创建) d2(别人创建但分享给我) d3(别人创建没分享)
    async def fake_ri_list(ws_id, resource_type=None, limit=None):
        return [
            {"resource_id": "d1", "creator_user_id": "me", "metadata": {"name": "a"}},
            {"resource_id": "d2", "creator_user_id": "bob", "metadata": {"name": "b"}},
            {"resource_id": "d3", "creator_user_id": "bob", "metadata": {"name": "c"}},
        ]

    async def fake_shared(ws, user, rt):
        return {"d2"}

    monkeypatch.setattr(crud.ri_repo, "list_by_workspace", fake_ri_list)
    monkeypatch.setattr(visibility, "shared_res_ids", fake_shared)

    rows = await crud.list_by_workspace(None, "ws1", creator_user_id="me")
    ids = {r["id"] for r in rows}
    assert ids == {"d1", "d2"}  # 我创建的 d1 + 分享给我的 d2; d3 排除
