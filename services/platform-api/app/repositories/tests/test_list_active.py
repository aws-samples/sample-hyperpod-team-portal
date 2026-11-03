"""list_active_by_workspace: 走 active-index GSI 查活跃行。"""
import pytest

from app.repositories import resource_index as ri
from app.adapters.ddb import tables


@pytest.mark.asyncio
async def test_list_active_queries_gsi(monkeypatch):
    captured = {}

    async def fake_query(table, *, key_condition_expression, expression_values,
                         index_name=None, scan_index_forward=True, limit=None,
                         **kw):
        captured.update(
            kc=key_condition_expression, vals=expression_values,
            index=index_name, limit=limit,
        )
        return [{"resource_id": "d1"}]

    monkeypatch.setattr(ri.base, "query", fake_query)
    out = await ri.list_active_by_workspace("ws-1", limit=200)
    assert out == [{"resource_id": "d1"}]
    assert captured["index"] == tables.RESOURCE_INDEX_GSI_ACTIVE
    assert captured["kc"] == "active_ws = :w"
    assert captured["vals"] == {":w": "ws-1"}
    assert captured["limit"] == 200
