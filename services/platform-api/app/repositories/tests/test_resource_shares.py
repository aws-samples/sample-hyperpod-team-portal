import app.main  # noqa: F401  避免循环 import


async def test_grant_puts_item_with_share_key(monkeypatch):
    from app.repositories import resource_shares as repo
    from app.adapters.ddb import tables

    captured = {}

    async def fake_put(table, item, ensure_new=False):
        captured["table"] = table
        captured["item"] = item

    monkeypatch.setattr(repo.base, "put_item", fake_put)

    row = await repo.grant(
        workspace_id="ws1", res_type="dev", res_id="d1",
        target_username="alice", shared_by="bob",
    )
    assert captured["table"] == tables.RESOURCE_SHARES_TABLE
    assert captured["item"]["share_key"] == "SHARE#dev#d1#USER#alice"
    assert captured["item"]["target_username"] == "alice"
    assert captured["item"]["shared_by"] == "bob"
    assert captured["item"]["res_type"] == "dev"
    assert captured["item"]["res_id"] == "d1"
    assert row["share_key"] == "SHARE#dev#d1#USER#alice"


async def test_list_by_resource_uses_begins_with(monkeypatch):
    from app.repositories import resource_shares as repo

    captured = {}

    async def fake_query(table, **kw):
        captured.update(kw)
        return [{"target_username": "alice"}]

    monkeypatch.setattr(repo.base, "query", fake_query)

    rows = await repo.list_by_resource("ws1", "dev", "d1")
    assert rows == [{"target_username": "alice"}]
    assert captured["expression_values"][":p"] == "SHARE#dev#d1#USER#"
    assert "begins_with" in captured["key_condition_expression"]


async def test_list_by_target_user_uses_gsi(monkeypatch):
    from app.repositories import resource_shares as repo
    from app.adapters.ddb import tables

    captured = {}

    async def fake_query(table, **kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(repo.base, "query", fake_query)

    await repo.list_by_target_user("alice", workspace_id="ws1")
    assert captured["index_name"] == tables.RESOURCE_SHARES_GSI_USER
    assert captured["expression_values"][":u"] == "alice"
    assert captured["expression_values"][":w"] == "ws1"


async def test_delete_by_resource_deletes_each(monkeypatch):
    from app.repositories import resource_shares as repo

    async def fake_query(table, **kw):
        return [
            {"share_key": "SHARE#dev#d1#USER#alice"},
            {"share_key": "SHARE#dev#d1#USER#bob"},
        ]

    deleted = []

    async def fake_delete(table, key, require_exists=False):
        deleted.append(key["share_key"])

    monkeypatch.setattr(repo.base, "query", fake_query)
    monkeypatch.setattr(repo.base, "delete_item", fake_delete)

    n = await repo.delete_by_resource("ws1", "dev", "d1")
    assert n == 2
    assert deleted == ["SHARE#dev#d1#USER#alice", "SHARE#dev#d1#USER#bob"]
