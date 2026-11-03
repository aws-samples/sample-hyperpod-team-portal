# app/modules/logs/tests/test_inference_insights.py
"""推理整任务搜索 Insights 查询串构造单测。"""

from __future__ import annotations

import pytest

from app.modules.logs.domain.insights_query import (
    InsightsQueryError,
    build_inference_whole_search_query,
)


def test_inference_query_scopes_by_logstream_prefix() -> None:
    q = build_inference_whole_search_query(
        endpoint_name="aaa-37ca18", query="", is_regex=False, limit=10000
    )
    # 用 @logStream 前缀圈定整 endpoint 的所有 pod stream
    assert (
        '@logStream like "FluentBit/kube.var.log.containers.aaa-37ca18-"' in q
    )
    # 主容器名 = endpoint name, 排掉 otel/sidecar
    assert 'kubernetes.container_name = "aaa-37ca18"' in q
    assert "sort @timestamp asc" in q
    assert "limit 10000" in q
    # 空 query 不加内容过滤
    assert "| filter log like" not in q


def test_inference_query_keyword_filter() -> None:
    q = build_inference_whole_search_query(
        endpoint_name="ep", query="OOM", is_regex=False, limit=100
    )
    assert '| filter log like "OOM"' in q


def test_inference_query_keyword_escapes_quotes() -> None:
    q = build_inference_whole_search_query(
        endpoint_name="ep", query='say "hi"', is_regex=False, limit=100
    )
    assert r'| filter log like "say \"hi\""' in q


def test_inference_query_regex_filter() -> None:
    q = build_inference_whole_search_query(
        endpoint_name="ep", query=r"err\d+", is_regex=True, limit=100
    )
    assert r"| filter log like /err\d+/" in q


def test_inference_query_bad_regex_raises() -> None:
    with pytest.raises(InsightsQueryError):
        build_inference_whole_search_query(
            endpoint_name="ep", query="(unclosed", is_regex=True, limit=100
        )


def test_inference_query_regex_slash_rejected() -> None:
    with pytest.raises(InsightsQueryError):
        build_inference_whole_search_query(
            endpoint_name="ep", query="a/b", is_regex=True, limit=100
        )
