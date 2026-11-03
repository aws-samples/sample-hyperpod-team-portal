"""list_by_workspace: DDB SK 是随机 UUID (与 created_at 无关), 截断必须发生在
应用层按 created_at 重排之后, 否则超过 limit 时截到的是随机一批而非最新一批。
"""
import pytest

from app.repositories import resource_index as ri


@pytest.mark.asyncio
async def test_list_by_workspace_truncates_by_created_at_not_ddb_order(monkeypatch):
    # 模拟 DDB 按 SK (随机 UUID) 返回的顺序: 故意与 created_at 顺序打乱。
    async def fake_query(table, *, limit=None, **kw):
        del table, kw
        return [
            {"resource_id": "old", "created_at": "2020-01-01T00:00:00Z"},
            {"resource_id": "newest", "created_at": "2024-01-03T00:00:00Z"},
            {"resource_id": "mid", "created_at": "2022-01-01T00:00:00Z"},
        ]

    monkeypatch.setattr(ri.base, "query", fake_query)

    out = await ri.list_by_workspace("ws-1", limit=2)

    # limit=2 必须保留最新创建的两条 (newest, mid), 丢弃最老的 (old) —
    # 不是 DDB 返回顺序里的前两条。
    assert [it["resource_id"] for it in out] == ["newest", "mid"]


@pytest.mark.asyncio
async def test_list_by_workspace_ddb_query_uses_scan_cap_not_caller_limit(monkeypatch):
    captured = {}

    async def fake_query(table, *, limit=None, **kw):
        del table, kw
        captured["limit"] = limit
        return []

    monkeypatch.setattr(ri.base, "query", fake_query)

    await ri.list_by_workspace("ws-1", limit=5)

    # DDB 层不能直接拿调用方的小 limit 去查 (那样等于按随机 UUID 序截断)。
    # 必须用远大于 limit 的防御性熔断值先捞全量, 再在应用层排序截断。
    assert captured["limit"] == ri._DDB_SCAN_CAP
    assert captured["limit"] > 5
