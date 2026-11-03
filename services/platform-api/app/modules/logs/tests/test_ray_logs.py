"""Ray (rayjob) 历史日志 stream 命名 + Insights query 单测 (照 test_llmd_logs.py)。"""

from __future__ import annotations

import pytest

from app.modules.logs.domain.insights_query import (
    InsightsQueryError,
    build_ray_whole_search_query,
)
from app.modules.logs.domain.stream_naming import (
    parse_ray_stream_name,
    ray_stream_prefix,
)

_P = "FluentBit/kube.var.log.containers."
_RC = "bob-ray-01-6jhqrk9o07-5czbk"  # rayClusterName (带随机后缀)


def _stream(pod: str, container: str, cid: str = "deadbeef00") -> str:
    return f"{_P}{pod}_hyperpod-ns-demo_{container}-{cid}.log"


class TestRayStreamPrefix:
    def test_prefix_uses_ray_cluster_name(self):
        assert ray_stream_prefix(_RC) == f"{_P}{_RC}-"


class TestParseRayStreamName:
    def test_head_pod_kept(self):
        s = _stream(f"{_RC}-head-2xslv", "ray-head")
        p = parse_ray_stream_name(s)
        assert p is not None
        assert p["pod_name"] == f"{_RC}-head-2xslv"
        assert p["container"] == "ray-head"
        assert p["container_id"] == "deadbeef00"

    def test_worker_pod_kept(self):
        s = _stream(f"{_RC}-worker-group-worker-49q4r", "ray-worker")
        p = parse_ray_stream_name(s)
        assert p is not None
        assert p["container"] == "ray-worker"

    def test_wait_gcs_ready_init_container_excluded(self):
        s = _stream(f"{_RC}-worker-group-worker-49q4r", "wait-gcs-ready")
        assert parse_ray_stream_name(s) is None

    def test_head_driver_log_tailer_sidecar_kept(self):
        # head 上的 driver 日志 sidecar (转写 job-driver-*.log) 也放行。
        # 容器名自带连字符, rfind("-") 须只切末尾的 container_id。
        s = _stream(f"{_RC}-head-7znnx", "driver-log-tailer")
        p = parse_ray_stream_name(s)
        assert p is not None
        assert p["pod_name"] == f"{_RC}-head-7znnx"
        assert p["container"] == "driver-log-tailer"
        assert p["container_id"] == "deadbeef00"

    def test_non_prefix_returns_none(self):
        assert parse_ray_stream_name("random-string") is None

    def test_empty_container_id_returns_none(self):
        s = f"{_P}{_RC}-head-x_ns_ray-head-.log"
        assert parse_ray_stream_name(s) is None


class TestBuildRayWholeSearchQuery:
    def test_prefix_and_dual_container_filter(self):
        q = build_ray_whole_search_query(
            ray_cluster_name=_RC, query="", is_regex=False, limit=100
        )
        assert f'@logStream like "{_P}{_RC}-"' in q
        assert 'kubernetes.container_name = "ray-head"' in q
        assert 'kubernetes.container_name = "ray-worker"' in q
        assert 'kubernetes.container_name = "driver-log-tailer"' in q
        assert "sort @timestamp asc" in q
        assert "limit 100" in q
        assert "filter log like" not in q

    def test_keyword_filter(self):
        q = build_ray_whole_search_query(
            ray_cluster_name=_RC, query="OOM", is_regex=False, limit=100
        )
        assert 'filter log like "OOM"' in q

    def test_quote_escaped(self):
        q = build_ray_whole_search_query(
            ray_cluster_name=_RC, query='say "hi"', is_regex=False, limit=100
        )
        assert '\\"hi\\"' in q

    def test_regex_filter(self):
        q = build_ray_whole_search_query(
            ray_cluster_name=_RC, query=r"err\d+", is_regex=True, limit=100
        )
        assert r"filter log like /err\d+/" in q

    def test_bad_regex_raises(self):
        with pytest.raises(InsightsQueryError):
            build_ray_whole_search_query(
                ray_cluster_name=_RC, query="[unclosed", is_regex=True, limit=100
            )

    def test_slash_regex_rejected(self):
        with pytest.raises(InsightsQueryError):
            build_ray_whole_search_query(
                ray_cluster_name=_RC, query="a/b", is_regex=True, limit=100
            )
