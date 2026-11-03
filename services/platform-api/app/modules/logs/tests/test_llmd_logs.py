# app/modules/logs/tests/test_llmd_logs.py
"""llm-d stream 命名解析 + 整任务搜索 Insights 查询串单测。

实测样本 (2026-07-30, cluster=hp-cluster-hypd-demo): k8s_name bob-1-replica-kamve2ruvr,
两类 pod — LWS(leader -multi-0 / worker -multi-0-1, 主容器 sglang) + gateway(Deployment
-gateway-<rs>-<hash>, 主容器 gateway)。sglang pod 带 worker-otel-collector sidecar (排除)。
"""

from __future__ import annotations

import pytest

from app.modules.logs.domain.insights_query import (
    InsightsQueryError,
    build_llmd_whole_search_query,
)
from app.modules.logs.domain.stream_naming import (
    llmd_stream_prefix,
    parse_llmd_stream_name,
)

_NS = "hyperpod-ns-demo"
_NAME = "bob-1-replica-kamve2ruvr"
_PREFIX = "FluentBit/kube.var.log.containers."


def _stream(pod: str, container: str, cid: str) -> str:
    return f"{_PREFIX}{pod}_{_NS}_{container}-{cid}.log"


# ---- 前缀 ----


def test_llmd_stream_prefix() -> None:
    assert llmd_stream_prefix(_NAME) == f"{_PREFIX}{_NAME}-"


# ---- 解析: LWS sglang (leader + worker) 保留 ----


def test_parse_lws_leader_sglang() -> None:
    pod = f"{_NAME}-multi-0"
    parsed = parse_llmd_stream_name(_stream(pod, "sglang", "04f050e22245"))
    assert parsed is not None
    assert parsed["pod_name"] == pod
    assert parsed["pod_short"] == "0"
    assert parsed["container"] == "sglang"
    assert parsed["container_id"] == "04f050e22245"


def test_parse_lws_worker_sglang() -> None:
    pod = f"{_NAME}-multi-0-1"
    parsed = parse_llmd_stream_name(_stream(pod, "sglang", "6a8ba433b646"))
    assert parsed is not None
    assert parsed["pod_short"] == "1"
    assert parsed["container"] == "sglang"


# ---- 解析: gateway 保留 ----


def test_parse_gateway() -> None:
    pod = f"{_NAME}-gateway-bbcfdcdf-vqqfr"
    parsed = parse_llmd_stream_name(_stream(pod, "gateway", "c0248a1dd299"))
    assert parsed is not None
    assert parsed["pod_name"] == pod
    assert parsed["pod_short"] == "vqqfr"
    assert parsed["container"] == "gateway"


# ---- 解析: otel-collector sidecar 排除 ----


def test_parse_worker_otel_collector_returns_none() -> None:
    pod = f"{_NAME}-multi-0"
    assert parse_llmd_stream_name(_stream(pod, "worker-otel-collector", "abc123")) is None


def test_parse_non_prefix_returns_none() -> None:
    assert parse_llmd_stream_name("not-a-fluentbit-stream") is None


def test_parse_empty_container_id_returns_none() -> None:
    pod = f"{_NAME}-multi-0"
    assert parse_llmd_stream_name(f"{_PREFIX}{pod}_{_NS}_sglang-.log") is None


# ---- Insights 查询串 ----


def test_llmd_query_scopes_by_logstream_prefix() -> None:
    q = build_llmd_whole_search_query(
        k8s_name=_NAME, query="", is_regex=False, limit=10000
    )
    assert f'@logStream like "{_PREFIX}{_NAME}-"' in q
    # 双容器过滤: sglang (LWS) + gateway (Deployment), 排 worker-otel-collector
    assert (
        'kubernetes.container_name = "sglang" or kubernetes.container_name = "gateway"'
        in q
    )
    assert "sort @timestamp asc" in q
    assert "limit 10000" in q
    assert "| filter log like" not in q


def test_llmd_query_keyword_filter() -> None:
    q = build_llmd_whole_search_query(
        k8s_name=_NAME, query="OOM", is_regex=False, limit=100
    )
    assert '| filter log like "OOM"' in q


def test_llmd_query_keyword_escapes_quotes() -> None:
    q = build_llmd_whole_search_query(
        k8s_name=_NAME, query='say "hi"', is_regex=False, limit=100
    )
    assert r'| filter log like "say \"hi\""' in q


def test_llmd_query_regex_filter() -> None:
    q = build_llmd_whole_search_query(
        k8s_name=_NAME, query=r"err\d+", is_regex=True, limit=100
    )
    assert r"| filter log like /err\d+/" in q


def test_llmd_query_bad_regex_raises() -> None:
    with pytest.raises(InsightsQueryError):
        build_llmd_whole_search_query(
            k8s_name=_NAME, query="(unclosed", is_regex=True, limit=100
        )


def test_llmd_query_regex_slash_rejected() -> None:
    with pytest.raises(InsightsQueryError):
        build_llmd_whole_search_query(
            k8s_name=_NAME, query="a/b", is_regex=True, limit=100
        )
