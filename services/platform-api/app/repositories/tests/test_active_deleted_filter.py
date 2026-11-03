"""软删行不进/不留稀疏 GSI active 视图 (总览过滤 deleted_at bug 修复)。

两层防御:
- 查询侧: list_active_by_workspace 带 attribute_not_exists(deleted_at) FilterExpression。
- 写入侧: update_status_if_changed 的 ConditionExpression 含 attribute_not_exists(deleted_at),
  软删行 informer reconcile 时跳过 (不复活 SET active_ws), 返回 "skipped" (不是 "absent")。
"""
from unittest.mock import AsyncMock

import pytest

from app.repositories import resource_index as ri
from app.adapters.ddb import tables


@pytest.mark.asyncio
async def test_list_active_filters_deleted(monkeypatch):
    """list_active_by_workspace 查询带 attribute_not_exists(deleted_at)。"""
    captured = {}

    async def fake_query(table, *, key_condition_expression, expression_values,
                         index_name=None, filter_expression=None,
                         scan_index_forward=True, limit=None, **kw):
        captured["index"] = index_name
        captured["filter"] = filter_expression
        return []

    monkeypatch.setattr(ri.base, "query", fake_query)
    await ri.list_active_by_workspace("ws-1")
    assert captured["index"] == tables.RESOURCE_INDEX_GSI_ACTIVE
    assert captured["filter"] == "attribute_not_exists(deleted_at)"


@pytest.mark.asyncio
async def test_status_update_condition_excludes_deleted(monkeypatch):
    """update_status_if_changed 的 ConditionExpression 含 attribute_not_exists(deleted_at):
    软删行 condition 失败 → 不更新 (不复活), 且因行存在(old 有值)返回 skipped 不是 absent。"""
    captured = {}

    async def fake_cond_update(table, key, *, update_expression,
                               condition_expression, expression_names,
                               expression_values):
        captured["cond"] = condition_expression
        # 模拟软删行: condition 失败但行存在 → ok=False, old=有值
        return False, {"workspace_id": "ws-1", "deleted_at": "2026-06-22T00:00:00Z"}

    monkeypatch.setattr(ri.base, "update_item_conditional", fake_cond_update)
    result = await ri.update_status_if_changed(
        workspace_id="ws-1", resource_type="inference", resource_id="i1",
        resource_version=5, md={"phase": "Running", "kueue_status": "Admitted"},
    )
    assert "attribute_not_exists(deleted_at)" in captured["cond"]
    assert result == "skipped"  # 软删行存在 → skipped, 不触发 create_stub 重建
