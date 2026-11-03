# app/modules/logs/tests/test_history_api.py
"""Logs · 历史日志端点单测 (FastAPI TestClient, mock orchestration + crud)."""

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
)

_FAKE_USER = {"user_id": "tester", "is_admin": True}


def _make_app() -> FastAPI:
    """logs router app, 鉴权依赖 override 成假用户 (端点鉴权另在 security 单测覆盖)."""
    app = FastAPI()
    app.include_router(logs_router_mod.logs_router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    app.dependency_overrides[get_current_user_allow_query] = lambda: _FAKE_USER
    return app


@pytest.fixture
def client(monkeypatch):
    async def fake_resolve(id_, current_user):
        # _resolve_log_ctx 现返回 dict (透出 task 行字段给懒加载缓存)。
        # cached_log_streams=None + kueue_status 非 finished → 走 list_fn 实时拉, 不回填。
        return {
            "k8s_job_name": "job-x",
            "cluster_tag": "ct",
            "cluster_arn": "arn:aws:sagemaker:us-west-2:1:cluster/cid",
            "kueue_status": "running",
            "workspace_id": "ws-1",
            "resource_id": "job-x",
            "cached_log_streams": None,
        }

    monkeypatch.setattr(logs_router_mod, "_resolve_log_ctx", fake_resolve)
    return TestClient(_make_app())


def test_list_streams(client, monkeypatch) -> None:
    async def fake_list(*, k8s_job_name, cluster_tag, cluster_arn):
        return [HistoryStreamInfo(
            stream_name="FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log",
            pod_short="p", seq=1, first_ts=1, last_ts=2)]

    monkeypatch.setattr(logs_router_mod.history, "list_streams", fake_list)
    r = client.get("/training-jobs/abc/log-streams")
    assert r.status_code == 200
    assert r.json()[0]["pod_short"] == "p"


def test_history_page(client, monkeypatch) -> None:
    async def fake_page(*, cluster_tag, cluster_arn, stream, token, load_dir,
                        anchor, start_ms, end_ms, limit=None):
        return HistoryLogPage(
            lines=[HistoryLogLine(time="t", stream="stdout", log="hi")],
            backward_token="b", forward_token="f")

    monkeypatch.setattr(logs_router_mod.history, "fetch_page", fake_page)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(f"/training-jobs/abc/logs/history?stream={valid}")
    assert r.status_code == 200
    assert r.json()["lines"][0]["log"] == "hi"


def test_history_page_limit_passed_through(client, monkeypatch) -> None:
    # limit 透传给 fetch_page: 不传 → None (由 fetch_page 内部兜底首屏/翻页);
    # 显式传 → 原样透传 (coding agent 一次性拉大量)。
    seen = {}

    async def fake_page(*, cluster_tag, cluster_arn, stream, token, load_dir,
                        anchor, start_ms, end_ms, limit=None):
        seen["limit"] = limit
        return HistoryLogPage(lines=[], backward_token="b", forward_token="f")

    monkeypatch.setattr(logs_router_mod.history, "fetch_page", fake_page)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"

    # 不传 limit → None
    r = client.get(f"/training-jobs/abc/logs/history?stream={valid}")
    assert r.status_code == 200
    assert seen["limit"] is None

    # 显式传 limit → 原样透传
    r = client.get(f"/training-jobs/abc/logs/history?stream={valid}&limit=10000")
    assert r.status_code == 200
    assert seen["limit"] == 10000


def test_history_page_limit_over_max_rejected(client) -> None:
    # 超过上限 (10000) → 422 (FastAPI Query le 校验)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(f"/training-jobs/abc/logs/history?stream={valid}&limit=10001")
    assert r.status_code == 422


def test_history_page_rejects_foreign_stream(client) -> None:
    foreign = "FluentBit/kube.var.log.containers.job-y-pods-h-p_ns_trainer-c.log"
    r = client.get(f"/training-jobs/abc/logs/history?stream={foreign}")
    assert r.status_code == 403


def test_history_search_routes_to_search_page(client, monkeypatch) -> None:
    # 带 query → 走 search_page (FilterLogEvents), 不碰 fetch_page。
    seen = {}

    async def fake_search(*, cluster_tag, cluster_arn, stream, query,
                          is_regex, start_ms, end_ms, token):
        seen.update(query=query, is_regex=is_regex, start_ms=start_ms, end_ms=end_ms)
        return HistoryLogPage(
            lines=[HistoryLogLine(time="t", stream="stdout", log="found")],
            next_token="tok", mode="search")

    async def fail_fetch(**_):
        raise AssertionError("should not call fetch_page when searching")

    monkeypatch.setattr(logs_router_mod.history, "search_page", fake_search)
    monkeypatch.setattr(logs_router_mod.history, "fetch_page", fail_fetch)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(
        f"/training-jobs/abc/logs/history?stream={valid}&query=ERROR&start_ms=100"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "search"
    assert body["lines"][0]["log"] == "found"
    assert seen["query"] == "ERROR" and seen["start_ms"] == 100


def test_history_time_only_routes_to_fetch_page(client, monkeypatch) -> None:
    # 无 query 但有时间窗 → 走 fetch_page (GetLogEvents 原生支持时间过滤且保双向),
    # 不走 search_page。时间窗 + load_dir 透传给 fetch_page。
    seen = {}

    async def fake_fetch(*, cluster_tag, cluster_arn, stream, token,
                         load_dir, anchor, start_ms, end_ms, limit=None):
        seen.update(load_dir=load_dir, start_ms=start_ms, end_ms=end_ms)
        return HistoryLogPage(
            lines=[HistoryLogLine(time="t", stream="stdout", log="x")],
            backward_token="b", forward_token="f", mode="browse")

    async def fail_search(**_):
        raise AssertionError("should not call search_page for time-only filter")

    monkeypatch.setattr(logs_router_mod.history, "fetch_page", fake_fetch)
    monkeypatch.setattr(logs_router_mod.history, "search_page", fail_search)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(
        f"/training-jobs/abc/logs/history?stream={valid}&end_ms=999&load_dir=forward"
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "browse"
    assert seen["end_ms"] == 999 and seen["load_dir"] == "forward"


def test_history_invalid_token_returns_409(client, monkeypatch) -> None:
    # 浏览态 token 误传给搜索 (FilterLogEvents) → AWS InvalidParameterException
    # → 适配器抛 InvalidPageTokenError → 端点 409 (让前端清 token 重搜)。
    from app.adapters.aws.cloudwatch_logs import InvalidPageTokenError

    async def boom(**_):
        raise InvalidPageTokenError("The specified nextToken is invalid.")

    monkeypatch.setattr(logs_router_mod.history, "search_page", boom)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(
        f"/training-jobs/abc/logs/history?stream={valid}&query=x&token=badtok"
    )
    assert r.status_code == 409


def test_history_regex_paren_returns_400(client, monkeypatch) -> None:
    from app.modules.logs.domain.filter_pattern import FilterPatternError

    async def boom(**_):
        raise FilterPatternError("no parens")

    monkeypatch.setattr(logs_router_mod.history, "search_page", boom)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(
        f"/training-jobs/abc/logs/history?stream={valid}&query=(a|b)&is_regex=true"
    )
    assert r.status_code == 400


def test_history_download_streams_text(client, monkeypatch) -> None:
    async def fake_iter(*, cluster_tag, cluster_arn, stream):
        yield "t1 [stdout] hello\n"
        yield "t2 [stderr] boom\n"

    monkeypatch.setattr(logs_router_mod.history, "iter_all_lines", fake_iter)
    valid = "FluentBit/kube.var.log.containers.job-x-pods-h-p_ns_trainer-c.log"
    r = client.get(f"/training-jobs/abc/logs/history/download?stream={valid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text == "t1 [stdout] hello\nt2 [stderr] boom\n"


def test_history_download_rejects_foreign_stream(client) -> None:
    foreign = "FluentBit/kube.var.log.containers.job-y-pods-h-p_ns_trainer-c.log"
    r = client.get(f"/training-jobs/abc/logs/history/download?stream={foreign}")
    assert r.status_code == 403


def test_log_streams_404_when_job_missing(monkeypatch) -> None:
    async def fake_get(_db, _id):
        return None

    monkeypatch.setattr(logs_router_mod.train_crud, "get", fake_get)

    c = TestClient(_make_app())
    r = c.get("/training-jobs/missing-id/log-streams")
    assert r.status_code == 404
