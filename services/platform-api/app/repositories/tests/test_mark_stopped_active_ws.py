"""mark_stopped_inference: 部分更新 4 字段 + REMOVE active_ws。"""
import pytest

from app.repositories import resource_index as ri


@pytest.mark.asyncio
async def test_mark_stopped_partial_update_removes_active_ws(monkeypatch):
    captured = {}

    async def fake_update(table, key, *, update_expression, expression_values=None,
                          expression_names=None, require_exists=True):
        captured["expr"] = update_expression
        captured["values"] = expression_values
        captured["names"] = expression_names
        return {}

    monkeypatch.setattr(ri.base, "update_item", fake_update)
    await ri.mark_stopped_inference("ws-1", "i1")

    expr = captured["expr"]
    assert "SET" in expr
    assert "REMOVE active_ws" in expr
    assert "#md.#phase = :phase" in expr
    assert captured["values"][":phase"] == "Stopped"
    assert captured["values"][":kueue_status"] == "Finished"
    assert captured["values"][":stop_requested"] is True
    assert ":endpoint_url" in captured["values"]
