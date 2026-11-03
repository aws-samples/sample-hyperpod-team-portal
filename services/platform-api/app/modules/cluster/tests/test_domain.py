"""Cluster domain 层单测 · 纯函数，无需 DB / K8s

测试目标:
- domain.health_check.derive_health_status (融合规则)
- domain.health_check.derive_sync_status (三态推导)
- domain.capacity.gpu_usage_pct / flavor_key_from_instance_type /
  instance_type_prefix_for_gpu / quota_usage_pct
"""

from __future__ import annotations

import pytest

from app.modules.cluster.domain.capacity import (
    flavor_key_from_instance_type,
    gpu_usage_pct,
    instance_type_prefix_for_gpu,
    quota_usage_pct,
)
from app.modules.cluster.domain.health_check import (
    derive_health_status,
    derive_sync_status,
)

# =====================================================================
# domain.health_check.derive_health_status
# =====================================================================


class TestDeriveHealthStatus:
    def test_sagemaker_schedulable_wins(self) -> None:
        # SM label 在前，即使 k8s NotReady 也优先 SM 的权威口径
        assert derive_health_status("Schedulable", k8s_ready=False) == "Schedulable"

    def test_sagemaker_unhealthy(self) -> None:
        assert derive_health_status("Unhealthy", k8s_ready=True) == "Unhealthy"

    def test_sagemaker_unschedulable_variants(self) -> None:
        assert (
            derive_health_status("Unschedulable", k8s_ready=True)
            == "UnschedulableSchedulingDisabled"
        )
        assert (
            derive_health_status("UnschedulablePendingReplacement", k8s_ready=True)
            == "UnschedulableSchedulingDisabled"
        )

    def test_fallback_to_k8s_ready_when_no_sm_label(self) -> None:
        assert derive_health_status(None, k8s_ready=True) == "Schedulable"
        assert derive_health_status(None, k8s_ready=False) == "Unhealthy"

    def test_empty_string_sagemaker_fallback(self) -> None:
        # 空字符串等同于无 label
        assert derive_health_status("", k8s_ready=True) == "Schedulable"
        assert derive_health_status("", k8s_ready=False) == "Unhealthy"

    def test_unknown_sagemaker_value_fallback(self) -> None:
        # 未知 SM 值 → 兜底走 K8s ready
        assert derive_health_status("Mystery", k8s_ready=True) == "Schedulable"
        assert derive_health_status("Mystery", k8s_ready=False) == "Unhealthy"


# =====================================================================
# domain.health_check.derive_sync_status
# =====================================================================


class TestDeriveSyncStatus:
    def test_non_hyperpod_always_aws_unavailable(self) -> None:
        assert (
            derive_sync_status(
                cluster_type="eks",
                db_ig_count=3,
                aws_ig_count=3,
                had_aws_error=False,
            )
            == "aws_unavailable"
        )

    def test_aws_error_gives_unavailable(self) -> None:
        assert (
            derive_sync_status(
                cluster_type="hyperpod",
                db_ig_count=3,
                aws_ig_count=3,
                had_aws_error=True,
            )
            == "aws_unavailable"
        )

    def test_aws_none_gives_unavailable(self) -> None:
        assert (
            derive_sync_status(
                cluster_type="hyperpod",
                db_ig_count=3,
                aws_ig_count=None,
                had_aws_error=False,
            )
            == "aws_unavailable"
        )

    def test_in_sync_when_counts_match(self) -> None:
        assert (
            derive_sync_status(
                cluster_type="hyperpod",
                db_ig_count=5,
                aws_ig_count=5,
                had_aws_error=False,
            )
            == "in_sync"
        )

    def test_out_of_sync_when_counts_differ(self) -> None:
        assert (
            derive_sync_status(
                cluster_type="hyperpod",
                db_ig_count=5,
                aws_ig_count=4,
                had_aws_error=False,
            )
            == "out_of_sync"
        )


# =====================================================================
# domain.capacity.gpu_usage_pct / quota_usage_pct
# =====================================================================


class TestUsagePct:
    @pytest.mark.parametrize(
        ("used", "total", "expected"),
        [
            (0, 0, 0.0),
            (10, 0, 0.0),  # total=0 不除零
            (0, 100, 0.0),
            (50, 100, 50.0),
            (25, 100, 25.0),
            (1, 3, 33.33),  # 保留 2 位小数
            (2, 3, 66.67),
            (100, 100, 100.0),
        ],
    )
    def test_gpu_usage_pct_rounded_two_decimals(
        self, used: int, total: int, expected: float
    ) -> None:
        assert gpu_usage_pct(used, total) == expected

    def test_quota_usage_pct_alias_of_gpu_usage_pct(self) -> None:
        # quota_usage_pct 与 gpu_usage_pct 语义相同，实现一致
        assert quota_usage_pct(50, 200) == gpu_usage_pct(50, 200)

    def test_negative_total_treated_as_zero(self) -> None:
        # 防御式：负 total 也返 0，不抛
        assert gpu_usage_pct(10, -5) == 0.0


# =====================================================================
# domain.capacity.flavor_key_from_instance_type
# =====================================================================


class TestFlavorKeyFromInstanceType:
    @pytest.mark.parametrize(
        ("instance_type", "expected"),
        [
            ("ml.g5.xlarge", "g5"),
            ("ml.g5.48xlarge", "g5"),
            ("ml.p5.48xlarge", "p5"),
            ("ml.p4d.24xlarge", "p4d"),
            ("ml.m5.xlarge", "cpu"),
            ("ml.c5.4xlarge", "cpu"),
            ("ml.r5.xlarge", "cpu"),
        ],
    )
    def test_parametrized(self, instance_type: str, expected: str) -> None:
        assert flavor_key_from_instance_type(instance_type) == expected

    def test_malformed_returns_unknown(self) -> None:
        assert flavor_key_from_instance_type("bad") == "unknown"
        assert flavor_key_from_instance_type("") == "unknown"

    def test_non_ml_prefix_still_parses_second_segment(self) -> None:
        # 不强校验 ml.* 前缀，按第二段 family 解析
        assert flavor_key_from_instance_type("ec2.g5.xlarge") == "g5"


# =====================================================================
# domain.capacity.instance_type_prefix_for_gpu
# =====================================================================


class TestInstanceTypePrefixForGpu:
    def test_known_gpu_types(self) -> None:
        assert instance_type_prefix_for_gpu("H100") == "ml.p5"
        assert instance_type_prefix_for_gpu("A100") == "ml.p4d"
        assert instance_type_prefix_for_gpu("A10G") == "ml.g5"

    def test_case_insensitive(self) -> None:
        assert instance_type_prefix_for_gpu("h100") == "ml.p5"
        assert instance_type_prefix_for_gpu("a10g") == "ml.g5"

    def test_unknown_returns_none(self) -> None:
        assert instance_type_prefix_for_gpu("T4") is None
        assert instance_type_prefix_for_gpu("") is None
