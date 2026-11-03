# app/modules/logs/tests/test_whole_task_search.py
"""Logs · 整任务搜索 (Insights) orchestration + 端点单测."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.modules.logs.api import router as logs_router_mod
from app.modules.logs.orchestration import fetch as fetch_orch


def _insights_event(ts: str, log: str, pod: str, stream: str = "stdout"):
    """构造一条 Insights event (list[{field,value}])。

    query select 的是 @timestamp/@logStream/log/stream (Insights 已自动解析信封),
    所以这里直接给这些字段; @logStream 用真实格式让 pod 提取生效。
    """
    log_stream = f"FluentBit/kube.var.log.containers.{pod}_ns_trainer-cid.log"
    return [
        {"field": "@timestamp", "value": ts},
        {"field": "@logStream", "value": log_stream},
        {"field": "log", "value": log},
        {"field": "stream", "value": stream},
    ]


@pytest.mark.asyncio
async def test_search_whole_task_parses_lines_and_pod(monkeypatch) -> None:
    async def fake_query(*, log_group, start_ms, end_ms, query, limit,
                         max_seconds=None, poll_interval=None):
        # 断言 query 用 label 精确匹配圈定整任务 + 只 trainer
        assert (
            '`kubernetes.labels.platform.hyperpod.io/training-job-id`'
            ' = "job-uuid"' in query
        )
        assert 'container_name = "trainer"' in query
        return [
            _insights_event("2026-07-02 01:00:00.000", "hello", "pod-a"),
            _insights_event("2026-07-02 01:00:01.000", "boom", "pod-b", "stderr"),
        ]

    monkeypatch.setattr(fetch_orch, "run_insights_query", fake_query)

    res = await fetch_orch.search_whole_task_logs(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        training_job_id="job-uuid", query="", is_regex=False,
        start_ms=None, end_ms=None,
    )
    assert [l.log for l in res.lines] == ["hello", "boom"]
    assert [l.pod for l in res.lines] == ["pod-a", "pod-b"]
    assert res.lines[1].stream == "stderr"
    assert res.truncated is False


@pytest.mark.asyncio
async def test_search_whole_task_truncated(monkeypatch) -> None:
    # 命中达 _WHOLE_TASK_LIMIT → truncated=True
    monkeypatch.setattr(fetch_orch, "_WHOLE_TASK_LIMIT", 3)

    ts = "2026-07-02 01:00:00.000"

    async def fake_query(*, log_group, start_ms, end_ms, query, limit,
                         max_seconds=None, poll_interval=None):
        assert limit == 3
        return [
            _insights_event(ts, "a", "p"),
            _insights_event(ts, "b", "p"),
            _insights_event(ts, "c", "p"),
        ]

    monkeypatch.setattr(fetch_orch, "run_insights_query", fake_query)

    res = await fetch_orch.search_whole_task_logs(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        training_job_id="j", query="x", is_regex=False,
        start_ms=None, end_ms=None,
    )
    assert len(res.lines) == 3
    assert res.truncated is True


@pytest.mark.asyncio
async def test_search_whole_task_default_window(monkeypatch) -> None:
    # 未给时间窗 → 默认近 24h (start < end, 且跨度 = 24h)
    seen = {}

    async def fake_query(*, log_group, start_ms, end_ms, query, limit,
                         max_seconds=None, poll_interval=None):
        seen.update(start=start_ms, end=end_ms)
        return []

    monkeypatch.setattr(fetch_orch, "run_insights_query", fake_query)

    await fetch_orch.search_whole_task_logs(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        training_job_id="j", query="", is_regex=False,
        start_ms=None, end_ms=None,
    )
    assert seen["end"] - seen["start"] == fetch_orch._WHOLE_TASK_DEFAULT_WINDOW_MS


@pytest.mark.asyncio
async def test_search_whole_inference_scopes_by_endpoint(monkeypatch) -> None:
    async def fake_query(*, log_group, start_ms, end_ms, query, limit,
                         max_seconds=None, poll_interval=None):
        # 推理走 @logStream 前缀圈定, 不用 label
        assert '@logStream like "FluentBit/kube.var.log.containers.ep-"' in query
        assert 'container_name = "ep"' in query
        return [
            _insights_event("2026-07-02 01:00:00.000", "hi", "ep-abc-xyz"),
        ]

    monkeypatch.setattr(fetch_orch, "run_insights_query", fake_query)

    res = await fetch_orch.search_whole_inference_logs(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        endpoint_name="ep", query="", is_regex=False,
        start_ms=None, end_ms=None,
    )
    assert [l.log for l in res.lines] == ["hi"]
    assert res.lines[0].pod == "ep-abc-xyz"
    assert res.truncated is False


# ===== 端点 =====

_FAKE_USER = {"user_id": "tester", "is_admin": True}


def _make_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(logs_router_mod.logs_router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER

    async def fake_resolve(id_, current_user):
        return {
            "k8s_job_name": "job-x",
            "cluster_tag": "ct",
            "cluster_arn": "arn:aws:sagemaker:us-west-2:1:cluster/cid",
            "kueue_status": "running",
            "workspace_id": "ws-1",
            "resource_id": "job-uuid",
            "cached_log_streams": None,
        }

    monkeypatch.setattr(logs_router_mod, "_resolve_log_ctx", fake_resolve)
    return TestClient(app)


def test_search_all_endpoint_ok(monkeypatch) -> None:
    from app.modules.logs.api.schemas import (
        WholeTaskLogLine,
        WholeTaskSearchResult,
    )

    seen = {}

    async def fake_search(*, cluster_tag, cluster_arn, training_job_id,
                          query, is_regex, start_ms, end_ms):
        seen.update(job=training_job_id, query=query, is_regex=is_regex)
        return WholeTaskSearchResult(
            lines=[WholeTaskLogLine(time="t", stream="stdout", log="x", pod="pod-a")],
            truncated=False,
        )

    monkeypatch.setattr(logs_router_mod, "search_whole_task_logs", fake_search)
    c = _make_client(monkeypatch)
    r = c.get("/training-jobs/abc/logs/search-all?query=err&is_regex=true")
    assert r.status_code == 200
    body = r.json()
    assert body["lines"][0]["pod"] == "pod-a"
    # 用 _resolve_log_ctx 的 resource_id 作为 job_id
    assert seen["job"] == "job-uuid" and seen["query"] == "err" and seen["is_regex"] is True


def test_search_all_endpoint_bad_regex_400(monkeypatch) -> None:
    from app.modules.logs.domain.insights_query import InsightsQueryError

    async def boom(**_):
        raise InsightsQueryError("正则语法错误")

    monkeypatch.setattr(logs_router_mod, "search_whole_task_logs", boom)
    c = _make_client(monkeypatch)
    r = c.get("/training-jobs/abc/logs/search-all?query=(bad&is_regex=true")
    assert r.status_code == 400


def _make_inf_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(logs_router_mod.logs_router)
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER

    async def fake_resolve(id_, current_user):
        return {
            "k8s_endpoint_name": "ep",
            "cluster_tag": "ct",
            "cluster_arn": "arn:aws:sagemaker:us-west-2:1:cluster/cid",
            "kueue_status": "running",
            "workspace_id": "ws-1",
            "resource_id": "inf-uuid",
            "cached_log_streams": None,
        }

    monkeypatch.setattr(logs_router_mod, "_resolve_inf_log_ctx", fake_resolve)
    return TestClient(app)


def test_inference_search_all_endpoint_ok(monkeypatch) -> None:
    from app.modules.logs.api.schemas import (
        WholeTaskLogLine,
        WholeTaskSearchResult,
    )

    seen = {}

    async def fake_search(*, cluster_tag, cluster_arn, endpoint_name,
                          query, is_regex, start_ms, end_ms):
        seen.update(ep=endpoint_name, query=query, is_regex=is_regex)
        return WholeTaskSearchResult(
            lines=[WholeTaskLogLine(time="t", stream="stdout", log="x", pod="ep-a")],
            truncated=False,
        )

    monkeypatch.setattr(logs_router_mod, "search_whole_inference_logs", fake_search)
    c = _make_inf_client(monkeypatch)
    r = c.get("/inferences/abc/logs/search-all?query=err&is_regex=true")
    assert r.status_code == 200
    assert r.json()["lines"][0]["pod"] == "ep-a"
    assert seen["ep"] == "ep" and seen["query"] == "err" and seen["is_regex"] is True


def test_inference_history_passes_search_params(monkeypatch) -> None:
    """有 query → 走 search_page；参数透传到位。"""
    from app.modules.logs.api import schemas as sch

    seen = {}

    async def fake_search_page(*, cluster_tag, cluster_arn, stream, query,
                               is_regex, start_ms, end_ms, token):
        seen.update(query=query, is_regex=is_regex, stream=stream)
        return sch.HistoryLogPage(lines=[], mode="search")

    monkeypatch.setattr(logs_router_mod.history, "search_page", fake_search_page)

    c = _make_inf_client(monkeypatch)
    stream = "FluentBit/kube.var.log.containers.ep-pod_ns_ep-cid.log"
    r = c.get(
        f"/inferences/abc/logs/history?stream={stream}&query=loss&is_regex=true"
    )
    assert r.status_code == 200
    assert seen["query"] == "loss" and seen["is_regex"] is True


def test_inference_history_browse_path(monkeypatch) -> None:
    """无 query → 走 fetch_page（浏览态）；load_dir/anchor 透传到位。"""
    from app.modules.logs.api import schemas as sch

    seen = {}

    async def fake_fetch_page(*, cluster_tag, cluster_arn, stream, token,
                              load_dir, anchor, start_ms, end_ms, limit=None):
        seen.update(load_dir=load_dir, anchor=anchor, stream=stream)
        return sch.HistoryLogPage(lines=[], mode="browse")

    monkeypatch.setattr(logs_router_mod.history, "fetch_page", fake_fetch_page)
    c = _make_inf_client(monkeypatch)
    stream = "FluentBit/kube.var.log.containers.ep-pod_ns_ep-cid.log"
    r = c.get(f"/inferences/abc/logs/history?stream={stream}&anchor=oldest")
    assert r.status_code == 200
    assert seen["anchor"] == "oldest"
