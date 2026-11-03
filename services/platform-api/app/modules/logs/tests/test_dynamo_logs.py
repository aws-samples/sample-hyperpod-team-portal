# app/modules/logs/tests/test_dynamo_logs.py
"""Dynamo (多机推理) stream 命名解析 + 整任务搜索 Insights 查询串单测。

实测样本 (2026-07-15, cluster=eks-hypd-demo): CR 名 test-multi-01-copy-z1aqmjhe1e,
frontend / worker-ldr / worker-wkr 三种 pod, 主容器均为 "main", sidecar = otel-collector。
"""

from __future__ import annotations

import pytest

from app.modules.logs.domain.insights_query import (
    InsightsQueryError,
    build_dynamo_whole_search_query,
)
from app.modules.logs.domain.stream_naming import (
    dynamo_stream_prefix,
    parse_dynamo_stream_name,
)

_NS = "hyperpod-ns-demo"
_CR = "test-multi-01-copy-z1aqmjhe1e"
_PREFIX = "FluentBit/kube.var.log.containers."


def _stream(pod: str, container: str, cid: str) -> str:
    return f"{_PREFIX}{pod}_{_NS}_{container}-{cid}.log"


# ---- 前缀 ----


def test_dynamo_stream_prefix() -> None:
    assert dynamo_stream_prefix(_CR) == f"{_PREFIX}{_CR}-"


# ---- 解析: 三种 pod 的主容器都保留 ----


def test_parse_frontend_main() -> None:
    pod = f"{_CR}-0-frontend-wckkj"
    parsed = parse_dynamo_stream_name(_stream(pod, "main", "e9fd6ac5abcd"))
    assert parsed is not None
    assert parsed["pod_name"] == pod
    assert parsed["pod_short"] == "wckkj"
    assert parsed["container"] == "main"
    assert parsed["container_id"] == "e9fd6ac5abcd"


def test_parse_worker_leader_main() -> None:
    pod = f"{_CR}-0-worker-0-worker-ldr-g8dw4"
    parsed = parse_dynamo_stream_name(_stream(pod, "main", "d97e1340"))
    assert parsed is not None
    assert parsed["pod_name"] == pod
    assert parsed["pod_short"] == "g8dw4"
    assert parsed["container"] == "main"


def test_parse_worker_main() -> None:
    pod = f"{_CR}-0-worker-0-worker-wkr-zkk5z"
    parsed = parse_dynamo_stream_name(_stream(pod, "main", "46a70d04"))
    assert parsed is not None
    assert parsed["pod_short"] == "zkk5z"


# ---- 解析: otel-collector sidecar 排除 ----


def test_parse_otel_collector_returns_none() -> None:
    pod = f"{_CR}-0-frontend-wckkj"
    assert parse_dynamo_stream_name(_stream(pod, "otel-collector", "abc123")) is None


def test_parse_non_prefix_returns_none() -> None:
    assert parse_dynamo_stream_name("not-a-fluentbit-stream") is None


def test_parse_empty_container_id_returns_none() -> None:
    pod = f"{_CR}-0-frontend-wckkj"
    # 尾部无 container_id
    assert parse_dynamo_stream_name(f"{_PREFIX}{pod}_{_NS}_main-.log") is None


# ---- Insights 查询串 ----


def test_dynamo_query_scopes_by_logstream_prefix() -> None:
    q = build_dynamo_whole_search_query(
        k8s_cr_name=_CR, query="", is_regex=False, limit=10000
    )
    assert f'@logStream like "{_PREFIX}{_CR}-"' in q
    # 主容器固定 "main" (与推理不同: 推理是 endpoint name)
    assert 'kubernetes.container_name = "main"' in q
    assert "sort @timestamp asc" in q
    assert "limit 10000" in q
    assert "| filter log like" not in q


def test_dynamo_query_keyword_filter() -> None:
    q = build_dynamo_whole_search_query(
        k8s_cr_name=_CR, query="OOM", is_regex=False, limit=100
    )
    assert '| filter log like "OOM"' in q


def test_dynamo_query_keyword_escapes_quotes() -> None:
    q = build_dynamo_whole_search_query(
        k8s_cr_name=_CR, query='say "hi"', is_regex=False, limit=100
    )
    assert r'| filter log like "say \"hi\""' in q


def test_dynamo_query_regex_filter() -> None:
    q = build_dynamo_whole_search_query(
        k8s_cr_name=_CR, query=r"err\d+", is_regex=True, limit=100
    )
    assert r"| filter log like /err\d+/" in q


def test_dynamo_query_bad_regex_raises() -> None:
    with pytest.raises(InsightsQueryError):
        build_dynamo_whole_search_query(
            k8s_cr_name=_CR, query="(unclosed", is_regex=True, limit=100
        )


def test_dynamo_query_regex_slash_rejected() -> None:
    with pytest.raises(InsightsQueryError):
        build_dynamo_whole_search_query(
            k8s_cr_name=_CR, query="a/b", is_regex=True, limit=100
        )
