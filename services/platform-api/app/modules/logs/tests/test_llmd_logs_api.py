# app/modules/logs/tests/test_llmd_logs_api.py
"""llm-d 历史日志端点单测 (FastAPI TestClient, mock orchestration + resolver)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import get_current_user, get_current_user_allow_query
from app.modules.logs.api import router as logs_router_mod
from app.modules.logs.api.schemas import (
    HistoryLogLine,
    HistoryLogPage,
    HistoryStreamInfo,
    WholeTaskLogLine,
    WholeTaskSearchResult,
)

_FAKE_USER = {"user_id": "tester", "is_admin": True}
_NAME = "bob-1-replica-kamve2ruvr"
_PREFIX = "FluentBit/kube.var.log.containers."
_STREAM = f"{_PREFIX}{_NAME}-multi-0_hyperpod-ns-demo_sglang-04f050e22245.log"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(logs_router_mod.logs_router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    app.dependency_overrides[get_current_user_allow_query] = lambda: _FAKE_USER
    return app


@pytest.fixture
def client(monkeypatch):
    async def fake_resolve(id_, current_user):
        return {
            "k8s_name": _NAME,
            "cluster_tag": "ct",
            "cluster_arn": "arn:aws:sagemaker:us-west-2:1:cluster/cid",
            "kueue_status": "running",
            "workspace_id": "ws-1",
            "resource_id": "llmd-1",
            "cached_log_streams": None,
        }

    monkeypatch.setattr(logs_router_mod, "_resolve_llmd_log_ctx", fake_resolve)
    return TestClient(_make_app())


def test_log_streams_ok(client, monkeypatch):
    async def fake_get_or_cache(**kwargs):
        return [
            HistoryStreamInfo(
                stream_name=_STREAM,
                pod_name=f"{_NAME}-multi-0",
                pod_short="0",
                first_ts=1,
                last_ts=2,
                seq=1,
            )
        ]

    monkeypatch.setattr(
        logs_router_mod.history, "get_or_cache_streams", fake_get_or_cache
    )
    r = client.get("/llmd/llmd-1/log-streams")
    assert r.status_code == 200
    assert r.json()[0]["stream_name"] == _STREAM


def test_history_browse_ok(client, monkeypatch):
    async def fake_fetch_page(**kwargs):
        return HistoryLogPage(
            lines=[HistoryLogLine(time="2026-07-30T00:00:00Z", stream="stdout", log="hi")],
            forward_token=None,
            backward_token=None,
            mode="browse",
        )

    monkeypatch.setattr(logs_router_mod.history, "fetch_page", fake_fetch_page)
    r = client.get("/llmd/llmd-1/logs/history", params={"stream": _STREAM})
    assert r.status_code == 200
    assert r.json()["lines"][0]["log"] == "hi"


def test_history_stream_prefix_guard_403(client):
    # stream 不以 llmd_stream_prefix(k8s_name) 开头 → 403 防越权
    bad = f"{_PREFIX}other-task-multi-0_ns_sglang-abc.log"
    r = client.get("/llmd/llmd-1/logs/history", params={"stream": bad})
    assert r.status_code == 403


def test_search_all_ok(client, monkeypatch):
    async def fake_search(**kwargs):
        return WholeTaskSearchResult(
            lines=[WholeTaskLogLine(time="t", stream="stdout", log="x", pod="p")],
            truncated=False,
        )

    monkeypatch.setattr(logs_router_mod, "search_whole_llmd_logs", fake_search)
    r = client.get("/llmd/llmd-1/logs/search-all", params={"query": "OOM"})
    assert r.status_code == 200
    assert r.json()["lines"][0]["log"] == "x"


def test_download_ok(client, monkeypatch):
    async def fake_iter(**kwargs):
        yield b"line1\n"
        yield b"line2\n"

    monkeypatch.setattr(logs_router_mod.history, "iter_all_lines", fake_iter)
    r = client.get(
        "/llmd/llmd-1/logs/history/download", params={"stream": _STREAM}
    )
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert b"line1" in r.content
