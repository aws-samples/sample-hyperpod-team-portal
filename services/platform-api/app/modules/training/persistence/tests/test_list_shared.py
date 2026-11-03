import app.main  # noqa: F401


async def test_list_by_workspace_includes_shared(monkeypatch):
    from app.modules.training.persistence import crud
    from app.modules.sharing import visibility

    async def fake_ri_list(ws_id, resource_type=None, limit=None):
        return [
            {"resource_id": "t1", "creator_user_id": "me", "metadata": {"name": "a"}},
            {"resource_id": "t2", "creator_user_id": "bob", "metadata": {"name": "b"}},
            {"resource_id": "t3", "creator_user_id": "bob", "metadata": {"name": "c"}},
        ]

    async def fake_shared(ws, user, rt):
        return {"t2"}

    monkeypatch.setattr(crud.ri_repo, "list_by_workspace", fake_ri_list)
    monkeypatch.setattr(visibility, "shared_res_ids", fake_shared)

    rows = await crud.list_by_workspace(None, "ws1", creator_user_id="me")
    ids = {r["id"] for r in rows}
    assert ids == {"t1", "t2"}  # 我创建的 t1 + 分享给我的 t2; t3 排除
