# app/modules/logs/tests/test_cw_adapter.py
"""CloudWatch logs adapter (describe/get) 单测 — mock aioboto3 client."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.adapters.aws import cloudwatch_logs as cw


@pytest.fixture(autouse=True)
def _reset_shared_logs_client():
    """每个测试前后重置进程内共享 logs client。

    adapter 用模块级缓存复用 client (连接池); 测试间若不重置, 第一个测试缓存的
    mock client 会被后续测试拿到, 导致后者 monkeypatch 的新 Session 不生效。
    """
    cw._logs_client = None
    cw._logs_client_stack = None
    yield
    cw._logs_client = None
    cw._logs_client_stack = None


def _patch_session(monkeypatch, fake_client) -> None:
    @asynccontextmanager
    async def _fake_ctx(*a, **k):
        yield fake_client

    class _FakeSession:
        def client(self, *a, **k):
            return _fake_ctx()

    monkeypatch.setattr(cw.aioboto3, "Session", lambda *a, **k: _FakeSession())


@pytest.mark.asyncio
async def test_describe_streams_paginates(monkeypatch) -> None:
    client = AsyncMock()
    client.describe_log_streams.side_effect = [
        {"logStreams": [{"logStreamName": "A", "firstEventTimestamp": 1,
                         "lastEventTimestamp": 2}], "nextToken": "t1"},
        {"logStreams": [{"logStreamName": "B", "firstEventTimestamp": 3,
                         "lastEventTimestamp": 4}]},
    ]
    _patch_session(monkeypatch, client)
    out = await cw.describe_log_streams_by_prefix(
        log_group="/lg", prefix="FluentBit/...x-pods-"
    )
    assert [s["logStreamName"] for s in out] == ["A", "B"]
    assert client.describe_log_streams.await_count == 2


@pytest.mark.asyncio
async def test_get_log_events_returns_tokens(monkeypatch) -> None:
    client = AsyncMock()
    client.get_log_events.return_value = {
        "events": [{"timestamp": 100, "message": "m1"}],
        "nextForwardToken": "f/1",
        "nextBackwardToken": "b/1",
    }
    _patch_session(monkeypatch, client)
    out = await cw.get_log_events(
        log_group="/lg", stream="A", start_from_head=False,
        next_token=None, limit=500,
    )
    assert out["events"][0]["message"] == "m1"
    assert out["next_forward_token"] == "f/1"
    assert out["next_backward_token"] == "b/1"
