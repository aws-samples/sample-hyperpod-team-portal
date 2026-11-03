"""list_by_workspace active_only 过滤 (后端 DDB 层排除已结束任务)。

KS-4: active_only=True 时, DDB FilterExpression 排除 kueue_status = finished
(informer 写的三态终态); kueue_status 缺失 (旧行未回填) 视为活跃保留。
"""
from unittest.mock import AsyncMock

import pytest

from app.repositories import resource_index as ri_repo


@pytest.mark.asyncio
async def test_active_only_adds_kueue_status_exclusion_filter(monkeypatch):
    captured = {}

    async def fake_query(table, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(ri_repo.base, "query", fake_query)

    await ri_repo.list_by_workspace("ws-1", active_only=True)

    fe = captured["filter_expression"]
    # 仍排除软删行
    assert "attribute_not_exists(deleted_at)" in fe
    # 排除终态任务: 新 Finished + 存量旧小写 finished 都排
    assert captured["expression_values"][":fin_new"] == "Finished"
    assert captured["expression_values"][":fin_old"] == "finished"
    assert captured["expression_names"]["#ks"] == "kueue_status"
    # 只依赖 kueue_status: 缺字段 (老数据/未写入/停止存量) 不算活跃, 不显示。
    # 活跃 = kueue_status 存在且非任一种 finished。
    assert "attribute_exists(#md.#ks)" in fe
    assert "#md.#ks <> :fin_new" in fe
    assert "#md.#ks <> :fin_old" in fe
    # 反转语义: 不再用 attribute_not_exists 把缺字段当活跃
    assert "attribute_not_exists(#md.#ks)" not in fe


@pytest.mark.asyncio
async def test_active_only_false_keeps_only_softdelete_filter(monkeypatch):
    captured = {}

    async def fake_query(table, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(ri_repo.base, "query", fake_query)

    await ri_repo.list_by_workspace("ws-1")  # 默认 active_only=False

    # 默认行为: 只过滤软删 (含停止行豁免), 不按 kueue_status 排除已结束任务
    fe = captured["filter_expression"]
    assert "attribute_not_exists(deleted_at)" in fe
    assert ":fin_new" not in str(captured["expression_values"].values())
    assert "#ks" not in str(captured["expression_names"].keys())


from app.modules.shared.kueue_status import is_active


def test_active_filter_accepts_six_states():
    # 新六态除 Finished 全活跃
    assert is_active("Queued") and is_active("Admitted") and is_active("Evicted")
    assert not is_active("Finished")
    # 存量旧值兼容
    assert is_active("started") and not is_active("finished")
