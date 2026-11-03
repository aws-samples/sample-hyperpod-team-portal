"""Unit tests · workspace.domain.namespace_spec (纯函数).

覆盖:
- validate_namespace 合法 / 非法边界
- normalize_namespace 回退 default
- manifest / NetworkPolicy / ResourceQuota 基础 shape
"""

from __future__ import annotations

import pytest

from app.modules.workspace.domain.namespace_spec import (
    build_default_network_policy,
    build_default_resource_quota,
    build_namespace_manifest,
    normalize_namespace,
    validate_namespace,
)

# ===== validate_namespace =====

@pytest.mark.parametrize(
    "ns",
    [
        "hyperpod-ns-team-a",
        "team-a-nlp",
        "a",
        "abc123",
        "a-1-b-2",
    ],
)
def test_validate_namespace_valid(ns: str) -> None:
    ok, err = validate_namespace(ns)
    assert ok is True
    assert err is None


@pytest.mark.parametrize(
    "ns,reason_hint",
    [
        ("", "空"),
        ("UPPER", "小写"),
        ("-leading", "首尾"),
        ("trailing-", "首尾"),
        ("a" * 64, "长度"),
        ("a_b", "小写"),
    ],
)
def test_validate_namespace_invalid(ns: str, reason_hint: str) -> None:
    ok, err = validate_namespace(ns)
    assert ok is False
    assert err is not None
    assert reason_hint in err or "namespace" in err


# ===== normalize_namespace =====

def test_normalize_namespace_default_when_none() -> None:
    assert normalize_namespace(None, default_from_name="team-a") == "hyperpod-ns-team-a"


def test_normalize_namespace_strips_then_prefixes() -> None:
    # 用户传 "team-a" → 强制前缀
    assert normalize_namespace("team-a", default_from_name="fallback") == "hyperpod-ns-team-a"


def test_normalize_namespace_idempotent_with_prefix() -> None:
    assert (
        normalize_namespace("hyperpod-ns-team-a", default_from_name="fallback")
        == "hyperpod-ns-team-a"
    )


# ===== build_namespace_manifest =====

def test_manifest_shape() -> None:
    m = build_namespace_manifest("hyperpod-ns-team-a", workspace_name="team-a")
    assert m["apiVersion"] == "v1"
    assert m["kind"] == "Namespace"
    assert m["metadata"]["name"] == "hyperpod-ns-team-a"
    labels = m["metadata"]["labels"]
    assert labels["hyperpod.amazonaws.com/managed-by"] == "platform-api"
    assert labels["hyperpod.amazonaws.com/team-name"] == "team-a"


def test_manifest_extra_labels_merged() -> None:
    m = build_namespace_manifest(
        "hyperpod-ns-team-a", workspace_name="team-a", labels={"custom/tag": "v1"}
    )
    labels = m["metadata"]["labels"]
    assert labels["custom/tag"] == "v1"
    assert labels["hyperpod.amazonaws.com/team-name"] == "team-a"


# ===== network policy / resource quota =====

def test_default_network_policy_is_deny_ingress() -> None:
    p = build_default_network_policy("hyperpod-ns-team-a")
    assert p["kind"] == "NetworkPolicy"
    assert p["metadata"]["namespace"] == "hyperpod-ns-team-a"
    assert p["spec"]["policyTypes"] == ["Ingress"]
    assert p["spec"]["podSelector"] == {}


def test_default_resource_quota_zero_by_default() -> None:
    q = build_default_resource_quota("hyperpod-ns-team-a")
    hard = q["spec"]["hard"]
    assert hard["requests.cpu"] == "0"
    assert hard["requests.memory"] == "0"
    assert hard["requests.nvidia.com/gpu"] == "0"


def test_default_resource_quota_custom_caps() -> None:
    q = build_default_resource_quota(
        "hyperpod-ns-team-a", cpu="100", memory="400Gi", gpu="8"
    )
    hard = q["spec"]["hard"]
    assert hard["requests.cpu"] == "100"
    assert hard["requests.memory"] == "400Gi"
    assert hard["requests.nvidia.com/gpu"] == "8"
