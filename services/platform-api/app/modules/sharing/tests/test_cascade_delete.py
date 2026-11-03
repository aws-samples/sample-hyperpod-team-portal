import app.main  # noqa: F401


async def test_delete_by_resource_called_on_dev_delete(monkeypatch):
    # 验证 delete_by_resource 被以正确参数调用 (删除流里的接线点)
    from app.repositories import resource_shares as repo

    calls = []

    async def fake_del(ws, rt, rid):
        calls.append((ws, rt, rid))
        return 0

    monkeypatch.setattr(repo, "delete_by_resource", fake_del)

    await repo.delete_by_resource("ws1", "dev", "d1")
    assert calls == [("ws1", "dev", "d1")]
