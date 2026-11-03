"""Unit tests · workspace.domain.aws_team_mapping (纯函数, 无 IO).

覆盖:
- ensure_aws_ns_prefix 幂等 + 前缀注入
- strip_aws_ns_prefix 反向映射 + 非 hyperpod-ns 原样返回
- team_name ↔ namespace 映射一致
- build_compute_quota_payload:
  - Count>0 仅发 Count
  - Count=0 + accelerators 发细粒度字段
  - LendAndBorrow 带 BorrowLimit
  - DontLend 不带 BorrowLimit
  - description 可选
- is_aws_not_found_error:
  - code 命中 NotFoundException / ResourceNotFoundException / ValidationException
  - message 含 "not found" 命中
  - 都不命中 False
"""

from __future__ import annotations

import pytest

from app.modules.workspace.domain.aws_team_mapping import (
    build_compute_quota_payload,
    ensure_aws_ns_prefix,
    is_aws_not_found_error,
    namespace_from_team_name,
    strip_aws_ns_prefix,
    team_name_from_workspace_name,
)

# ===== ensure_aws_ns_prefix =====

def test_ensure_aws_ns_prefix_adds_when_missing() -> None:
    assert ensure_aws_ns_prefix("team-a") == "hyperpod-ns-team-a"


def test_ensure_aws_ns_prefix_idempotent() -> None:
    assert ensure_aws_ns_prefix("hyperpod-ns-team-a") == "hyperpod-ns-team-a"


def test_ensure_aws_ns_prefix_empty_string_edge() -> None:
    # 空串退化到只给前缀 · 由上游 schema 保证不传空
    assert ensure_aws_ns_prefix("") == "hyperpod-ns-"


# ===== strip_aws_ns_prefix =====

def test_strip_aws_ns_prefix_removes_prefix() -> None:
    assert strip_aws_ns_prefix("hyperpod-ns-team-a") == "team-a"


def test_strip_aws_ns_prefix_no_prefix_original() -> None:
    # 不带前缀的 namespace 原样返 (数据异常, 让上层自己处理)
    assert strip_aws_ns_prefix("random-ns") == "random-ns"


# ===== team_name ↔ namespace round-trip =====

def test_team_name_namespace_roundtrip() -> None:
    name = "team-a-nlp"
    ns = namespace_from_team_name(team_name_from_workspace_name(name))
    assert ns == "hyperpod-ns-team-a-nlp"
    assert strip_aws_ns_prefix(ns) == name


# ===== build_compute_quota_payload =====

_CLUSTER_ARN = "arn:aws:sagemaker:us-west-2:123:cluster/demo"


def test_payload_only_count_when_count_positive() -> None:
    payload = build_compute_quota_payload(
        name="team-a",
        cluster_arn=_CLUSTER_ARN,
        resources=[
            {
                "instance_type": "ml.p5.48xlarge",
                "count": 2,
                "accelerators": 8,  # 应被忽略 (Count 互斥)
                "v_cpu": 192.0,
                "memory_in_gi_b": 2048.0,
            }
        ],
        sharing_strategy="LendAndBorrow",
        preempt_team_tasks="LowerPriority",
        fair_share_weight=10,
        description=None,
    )
    resources = payload["ComputeQuotaConfig"]["ComputeQuotaResources"]
    assert resources == [{"InstanceType": "ml.p5.48xlarge", "Count": 2}]


def test_payload_fine_grained_when_count_zero() -> None:
    payload = build_compute_quota_payload(
        name="team-a",
        cluster_arn=_CLUSTER_ARN,
        resources=[
            {
                "instance_type": "ml.g5.xlarge",
                "count": 0,
                "accelerators": 2,
                "v_cpu": 8.0,
                "memory_in_gi_b": 32.0,
            }
        ],
        sharing_strategy="Lend",
        preempt_team_tasks="Never",
        fair_share_weight=5,
        description="team for ml experiments",
    )
    resources = payload["ComputeQuotaConfig"]["ComputeQuotaResources"]
    assert resources == [
        {
            "InstanceType": "ml.g5.xlarge",
            "Count": 0,
            "Accelerators": 2,
            "VCpu": 8.0,
            "MemoryInGiB": 32.0,
        }
    ]
    assert payload["Description"] == "team for ml experiments"


def test_payload_lend_strategies_carry_borrow_limit() -> None:
    for strategy in ("LendAndBorrow", "Lend"):
        payload = build_compute_quota_payload(
            name="team-a",
            cluster_arn=_CLUSTER_ARN,
            resources=[],
            sharing_strategy=strategy,
            preempt_team_tasks="LowerPriority",
            fair_share_weight=10,
            description=None,
        )
        sharing = payload["ComputeQuotaConfig"]["ResourceSharingConfig"]
        assert sharing["Strategy"] == strategy
        assert sharing["BorrowLimit"] == 50


def test_payload_dontlend_has_no_borrow_limit() -> None:
    payload = build_compute_quota_payload(
        name="team-a",
        cluster_arn=_CLUSTER_ARN,
        resources=[],
        sharing_strategy="DontLend",
        preempt_team_tasks="LowerPriority",
        fair_share_weight=10,
        description=None,
    )
    sharing = payload["ComputeQuotaConfig"]["ResourceSharingConfig"]
    assert sharing == {"Strategy": "DontLend"}


def test_payload_base_fields_shape() -> None:
    payload = build_compute_quota_payload(
        name="team-a",
        cluster_arn=_CLUSTER_ARN,
        resources=[],
        sharing_strategy="LendAndBorrow",
        preempt_team_tasks="LowerPriority",
        fair_share_weight=10,
        description=None,
    )
    assert payload["Name"] == "team-a"
    assert payload["ClusterArn"] == _CLUSTER_ARN
    assert payload["ActivationState"] == "Enabled"
    assert payload["ComputeQuotaTarget"] == {"TeamName": "team-a", "FairShareWeight": 10}
    assert payload["ComputeQuotaConfig"]["PreemptTeamTasks"] == "LowerPriority"
    assert "Description" not in payload  # 空时不加 key


# ===== is_aws_not_found_error =====

@pytest.mark.parametrize(
    "code,message,expected",
    [
        ("ResourceNotFoundException", "quota xxx not found", True),
        ("NotFoundException", "", True),
        ("ValidationException", "compute quota id is invalid", True),
        ("AccessDeniedException", "user cannot perform", False),
        ("ThrottlingException", "rate exceeded", False),
        ("UnknownCode", "Not Found", True),          # message 命中
        ("UnknownCode", "NOT FOUND", True),          # 大小写不敏感
        ("UnknownCode", "server error", False),
    ],
)
def test_is_aws_not_found_error(code: str, message: str, expected: bool) -> None:
    assert is_aws_not_found_error(code, message) is expected
