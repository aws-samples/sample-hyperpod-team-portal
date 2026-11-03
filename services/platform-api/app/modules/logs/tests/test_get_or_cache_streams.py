"""get_or_cache_streams: 懒加载缓存编排。"""
from unittest.mock import AsyncMock

import pytest

from app.modules.logs.api.schemas import HistoryStreamInfo
from app.modules.logs.orchestration import history


def _si(name="s1"):
    return HistoryStreamInfo(stream_name=name, pod_short="abc", seq=1, first_ts=100, last_ts=200)


@pytest.mark.asyncio
async def test_cache_hit_no_cloudwatch(monkeypatch):
    list_fn = AsyncMock()
    ubf = AsyncMock()
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    cached = [{"stream_name": "s1", "pod_short": "abc", "seq": 1, "first_ts": 100, "last_ts": 200}]
    out = await history.get_or_cache_streams(
        cached_log_streams=cached,
        kueue_status="finished",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={},
    )
    list_fn.assert_not_awaited()
    ubf.assert_not_awaited()
    assert [s.stream_name for s in out] == ["s1"]


@pytest.mark.asyncio
async def test_miss_finished_writes_cache(monkeypatch):
    list_fn = AsyncMock(return_value=[_si("s1"), _si("s2")])
    ubf = AsyncMock()
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    out = await history.get_or_cache_streams(
        cached_log_streams=None,
        kueue_status="finished",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={"k8s_job_name": "j"},
    )
    list_fn.assert_awaited_once()
    ubf.assert_awaited_once()
    fields = ubf.call_args.kwargs["fields"]
    assert len(fields["log_streams"]) == 2
    assert fields["log_streams"][0]["stream_name"] == "s1"
    assert [s.stream_name for s in out] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_miss_finished_new_uppercase_writes_cache(monkeypatch):
    # 新六态 "Finished" (大写) 也应触发回填 (is_terminal 认它)
    list_fn = AsyncMock(return_value=[_si("s1")])
    ubf = AsyncMock()
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    await history.get_or_cache_streams(
        cached_log_streams=None,
        kueue_status="Finished",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={},
    )
    ubf.assert_awaited_once()


@pytest.mark.asyncio
async def test_miss_evicted_no_write(monkeypatch):
    # Evicted 是中间态, 不是终态 → 不回填缓存
    list_fn = AsyncMock(return_value=[_si("s1")])
    ubf = AsyncMock()
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    await history.get_or_cache_streams(
        cached_log_streams=None,
        kueue_status="Evicted",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={},
    )
    ubf.assert_not_awaited()


@pytest.mark.asyncio
async def test_miss_not_finished_no_write(monkeypatch):
    list_fn = AsyncMock(return_value=[_si("s1")])
    ubf = AsyncMock()
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    out = await history.get_or_cache_streams(
        cached_log_streams=None,
        kueue_status="started",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={},
    )
    list_fn.assert_awaited_once()
    ubf.assert_not_awaited()
    assert [s.stream_name for s in out] == ["s1"]


@pytest.mark.asyncio
async def test_over_cap_no_write(monkeypatch):
    big = [_si(f"s{i}") for i in range(history.MAX_CACHED_STREAMS + 1)]
    list_fn = AsyncMock(return_value=big)
    ubf = AsyncMock()
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    out = await history.get_or_cache_streams(
        cached_log_streams=None,
        kueue_status="finished",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={},
    )
    ubf.assert_not_awaited()
    assert len(out) == history.MAX_CACHED_STREAMS + 1


@pytest.mark.asyncio
async def test_cache_write_failure_not_blocking(monkeypatch):
    list_fn = AsyncMock(return_value=[_si("s1")])
    ubf = AsyncMock(side_effect=RuntimeError("ddb down"))
    monkeypatch.setattr(history.ri_repo, "update_business_fields", ubf)
    out = await history.get_or_cache_streams(
        cached_log_streams=None,
        kueue_status="finished",
        workspace_id="ws-1",
        resource_id="r1",
        resource_type="train",
        list_fn=list_fn,
        list_fn_kwargs={},
    )
    assert [s.stream_name for s in out] == ["s1"]
