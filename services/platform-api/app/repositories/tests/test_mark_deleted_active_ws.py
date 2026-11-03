"""mark_deleted 同时 REMOVE active_ws (删除即出 GSI)。"""
import pytest

from app.repositories import resource_index as ri


@pytest.mark.asyncio
async def test_mark_deleted_removes_active_ws(monkeypatch):
    captured = {}

    async def fake_update(table, key, update_expression, expression_values=None,
                          *, expression_names=None, require_exists=True):
        captured["expr"] = update_expression
        captured["values"] = expression_values
        captured["names"] = expression_names
        return {}

    monkeypatch.setattr(ri.base, "update_item", fake_update)
    await ri.mark_deleted("ws-1", "dev", "d1")
    assert "SET deleted_at = :d" in captured["expr"]
    assert "REMOVE active_ws" in captured["expr"]
    assert "#md.#ks = :finished" in captured["expr"]
    assert captured["values"][":finished"] == "Finished"
    assert captured["names"]["#ks"] == "kueue_status"
    assert captured["names"]["#md"] == "metadata"
