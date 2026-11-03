"""开发机 (devinstance) 历史日志 stream 命名 + Insights query 单测 (照 test_dynamo_logs.py)。"""

from __future__ import annotations

import pytest

from app.modules.logs.domain.stream_naming import (
    devinstance_stream_prefix,
    parse_devinstance_stream_name,
)

_P = "FluentBit/kube.var.log.containers."
_WS = "alice-dev01-m7cpglvzre"  # k8s_workspace_name (CR 名)


def _stream(container: str, pod_hash: str = "c682s", cid: str = "deadbeef00") -> str:
    # pod 名 = workspace-{CR名}-{rs_hash}-{pod_hash}
    pod = f"workspace-{_WS}-698c5f86b5-{pod_hash}"
    return f"{_P}{pod}_hyperpod-ns-demo_{container}-{cid}.log"


class TestDevinstanceStreamPrefix:
    def test_prefix_has_workspace_literal(self):
        assert devinstance_stream_prefix(_WS) == f"{_P}workspace-{_WS}-"


class TestParseDevinstanceStreamName:
    def test_workspace_container_kept(self):
        p = parse_devinstance_stream_name(_stream("workspace"))
        assert p is not None
        assert p["pod_name"] == f"workspace-{_WS}-698c5f86b5-c682s"
        assert p["container"] == "workspace"
        assert p["container_id"] == "deadbeef00"
        assert p["pod_short"] == "c682s"

    def test_direct_ssh_init_container_kept(self):
        p = parse_devinstance_stream_name(_stream("direct-ssh-init"))
        assert p is not None
        assert p["container"] == "direct-ssh-init"
        assert p["container_id"] == "deadbeef00"
        assert p["pod_short"] == "c682s"

    def test_empty_container_id_returns_none(self):
        bad = f"{_P}workspace-{_WS}-698c5f86b5-c682s_hyperpod-ns-demo_workspace-.log"
        assert parse_devinstance_stream_name(bad) is None

    def test_ssm_agent_sidecar_excluded(self):
        assert parse_devinstance_stream_name(_stream("ssm-agent-sidecar")) is None

    def test_workspace_init_container_excluded(self):
        assert parse_devinstance_stream_name(_stream("workspace-init-container")) is None

    def test_non_prefix_returns_none(self):
        assert parse_devinstance_stream_name("random-string") is None


from app.modules.logs.domain.insights_query import (
    InsightsQueryError,
    build_devinstance_whole_search_query,
)


class TestBuildDevinstanceWholeSearchQuery:
    def test_prefix_and_dual_container_filter(self):
        q = build_devinstance_whole_search_query(
            k8s_workspace_name=_WS, query="", is_regex=False, limit=100
        )
        assert f'@logStream like "{_P}workspace-{_WS}-"' in q
        assert 'kubernetes.container_name = "workspace"' in q
        assert 'kubernetes.container_name = "direct-ssh-init"' in q
        assert "sort @timestamp asc" in q
        assert "limit 100" in q
        assert "filter log like" not in q

    def test_keyword_filter(self):
        q = build_devinstance_whole_search_query(
            k8s_workspace_name=_WS, query="ssh", is_regex=False, limit=100
        )
        assert 'filter log like "ssh"' in q

    def test_bad_regex_raises(self):
        with pytest.raises(InsightsQueryError):
            build_devinstance_whole_search_query(
                k8s_workspace_name=_WS, query="[unclosed", is_regex=True, limit=100
            )

    def test_keyword_escapes_quotes(self):
        q = build_devinstance_whole_search_query(
            k8s_workspace_name=_WS, query='say "hi"', is_regex=False, limit=100
        )
        assert r'filter log like "say \"hi\""' in q

    def test_regex_filter(self):
        q = build_devinstance_whole_search_query(
            k8s_workspace_name=_WS, query=r"err\d+", is_regex=True, limit=100
        )
        assert r"filter log like /err\d+/" in q

    def test_slash_regex_rejected(self):
        with pytest.raises(InsightsQueryError):
            build_devinstance_whole_search_query(
                k8s_workspace_name=_WS, query="a/b", is_regex=True, limit=100
            )
