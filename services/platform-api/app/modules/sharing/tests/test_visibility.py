import app.main  # noqa: F401


async def test_shared_res_ids_filters_by_type(monkeypatch):
    from app.modules.sharing import visibility

    async def fake_list(username, workspace_id=None):
        return [
            {"res_type": "dev", "res_id": "d1"},
            {"res_type": "dev", "res_id": "d2"},
            {"res_type": "train", "res_id": "t1"},
        ]

    monkeypatch.setattr(visibility.shares_repo, "list_by_target_user", fake_list)

    dev_ids = await visibility.shared_res_ids("ws1", "alice", "dev")
    assert dev_ids == {"d1", "d2"}
    train_ids = await visibility.shared_res_ids("ws1", "alice", "train")
    assert train_ids == {"t1"}


async def test_shared_res_ids_empty(monkeypatch):
    from app.modules.sharing import visibility

    async def fake_list(username, workspace_id=None):
        return []

    monkeypatch.setattr(visibility.shares_repo, "list_by_target_user", fake_list)
    assert await visibility.shared_res_ids("ws1", "alice", "dev") == set()
