"""Logs · domain 层单测 (纯函数)."""

from __future__ import annotations

import pytest

from app.modules.logs.domain.event_parsing import parse_insights_event
from app.modules.logs.domain.insights_query import (
    InsightsQueryError,
    build_training_job_query,
    build_whole_task_search_query,
)
from app.modules.logs.domain.log_group_naming import (
    build_log_group,
    cluster_id_suffix_from_arn,
)


def test_cluster_id_suffix_from_arn() -> None:
    arn = "arn:aws:sagemaker:us-west-2:123456789012:cluster/abcd1234efgh"
    assert cluster_id_suffix_from_arn(arn) == "abcd1234efgh"


def test_build_log_group() -> None:
    arn = "arn:aws:sagemaker:us-west-2:123456789012:cluster/abcd1234efgh"
    lg = build_log_group("demo-cluster", arn)
    assert lg == "/aws/sagemaker/Clusters/demo-cluster/abcd1234efgh"


def test_build_training_job_query_no_container() -> None:
    q = build_training_job_query(
        training_job_id="abc-123", container=None, limit=100
    )
    assert '@message like "abc-123"' in q
    assert "container_name" not in q
    assert "limit 100" in q
    assert "sort @timestamp asc" in q


def test_build_training_job_query_with_container() -> None:
    q = build_training_job_query(
        training_job_id="abc-123", container="trainer", limit=50
    )
    # 关键: 匹配 JSON 切片 "container_name":"trainer (嵌在单引号字符串里)
    assert 'container_name":"trainer' in q
    # 关键: container_clause 用 `and @message like` 连接
    assert "and @message like 'container_name" in q


def test_build_whole_task_search_no_query() -> None:
    q = build_whole_task_search_query(
        training_job_id="job-1", query="", is_regex=False, limit=2000
    )
    # label 精确匹配圈定整任务 (反引号包整路径)
    assert (
        '`kubernetes.labels.platform.hyperpod.io/training-job-id` = "job-1"' in q
    )
    assert 'kubernetes.container_name = "trainer"' in q  # 只 trainer
    assert "filter log like" not in q  # 无内容过滤
    assert "@logStream" in q  # 返回来源 pod
    assert "limit 2000" in q


def test_build_whole_task_search_keyword() -> None:
    q = build_whole_task_search_query(
        training_job_id="job-1", query="train_loss", is_regex=False, limit=100
    )
    assert 'filter log like "train_loss"' in q  # 子串, 双引号


def test_build_whole_task_search_regex() -> None:
    q = build_whole_task_search_query(
        training_job_id="job-1", query=r"loss=\d+", is_regex=True, limit=100
    )
    assert r"filter log like /loss=\d+/" in q  # 正则, 斜杠


def test_build_whole_task_search_keyword_escapes_quote() -> None:
    q = build_whole_task_search_query(
        training_job_id="job-1", query='say "hi"', is_regex=False, limit=10
    )
    assert r'log like "say \"hi\""' in q  # 双引号转义防闭合


def test_build_whole_task_search_bad_regex_raises() -> None:
    with pytest.raises(InsightsQueryError):
        build_whole_task_search_query(
            training_job_id="j", query="(unclosed", is_regex=True, limit=10
        )


def test_build_whole_task_search_regex_slash_raises() -> None:
    # 斜杠会闭合 like /.../ 字面量, 禁止
    with pytest.raises(InsightsQueryError):
        build_whole_task_search_query(
            training_job_id="j", query="a/b", is_regex=True, limit=10
        )


def test_parse_insights_event_valid_json_envelope() -> None:
    ev = [
        {"field": "@timestamp", "value": "2026-05-11 09:53:48.645"},
        {
            "field": "@message",
            "value": (
                '{"log":"Epoch 1 done\\n","stream":"stdout",'
                '"kubernetes":{"pod_name":"hpj-pod-0",'
                '"container_name":"trainer","host":"hyperpod-i-0"}}'
            ),
        },
    ]
    line = parse_insights_event(ev)
    assert line is not None
    assert line.message == "Epoch 1 done"
    assert line.stream == "stdout"
    assert line.pod == "hpj-pod-0"
    assert line.container == "trainer"
    assert line.node == "hyperpod-i-0"
    assert line.timestamp_ms > 0


def test_parse_insights_event_missing_timestamp_returns_none() -> None:
    ev = [{"field": "@message", "value": "plain text"}]
    assert parse_insights_event(ev) is None


def test_parse_insights_event_non_json_message() -> None:
    ev = [
        {"field": "@timestamp", "value": "2026-05-11 09:53:48.645"},
        {"field": "@message", "value": "plain non-json log line"},
    ]
    line = parse_insights_event(ev)
    assert line is not None
    assert line.message == "plain non-json log line"
    assert line.stream == "stdout"  # default


def test_backward_compat_shim() -> None:
    from app.modules.logs import schemas, service

    assert hasattr(service, "LogsServiceError")
    assert hasattr(service, "fetch_training_logs")
    assert hasattr(service, "build_log_group")
    assert hasattr(schemas, "LogLine")
    assert hasattr(schemas, "LogResponse")
