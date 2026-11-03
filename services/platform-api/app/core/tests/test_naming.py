"""app/core/naming 单测.

重点守 TRAINING_NAME_MAX: 训练任务名上限由 operator webhook 卡, 比 DNS 的 63 严,
算错要等提交才被拒 (报错是 K8s 原文, 用户看不懂).
"""

from __future__ import annotations

import re

from app.core.naming import (
    INFERENCE_NAME_MAX,
    TRAINING_NAME_MAX,
    make_dns_name,
    sanitize_dns_label,
)

# 派生名形状: 前缀 + '-' + 10 位 a-z0-9
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*-[a-z0-9]{10}$")


class TestTrainingNameMax:
    def test_constant_is_40(self) -> None:
        """40 是实测值 (40 过 / 41 拒), 改它前先重测."""
        assert TRAINING_NAME_MAX == 40

    def test_max_display_name_lands_exactly_on_limit(self) -> None:
        """29 字符显示名 → 派生名恰好 40."""
        name = make_dns_name("a" * 29, fallback="train", max_total=TRAINING_NAME_MAX)
        assert len(name) == 40
        assert _NAME_RE.match(name)

    def test_never_exceeds_max_total_even_when_over_long(self) -> None:
        """超长显示名要截断, 不能吐出超限的名字."""
        name = make_dns_name("a" * 200, fallback="train", max_total=TRAINING_NAME_MAX)
        assert len(name) <= TRAINING_NAME_MAX

    def test_default_max_total_unchanged_for_other_callers(self) -> None:
        """不传 max_total 仍按 DNS 63 (开发机走这条, 行为不能变)."""
        name = make_dns_name("a" * 200, fallback="dev")
        assert len(name) == 63


class TestInferenceNameMax:
    def test_same_as_training(self) -> None:
        """推理硬限其实是 63 (CRD spec.modelName), 取 40 是为了与训练共用一套显示名
        规则。两者必须相等, 否则前端得按模块分别提示。"""
        assert INFERENCE_NAME_MAX == TRAINING_NAME_MAX == 40

    def test_max_display_name_lands_exactly_on_limit(self) -> None:
        name = make_dns_name("a" * 29, fallback="infer", max_total=INFERENCE_NAME_MAX)
        assert len(name) == 40
        assert _NAME_RE.match(name)

    def test_never_exceeds_max_total_even_when_over_long(self) -> None:
        name = make_dns_name("a" * 200, fallback="infer", max_total=INFERENCE_NAME_MAX)
        assert len(name) <= INFERENCE_NAME_MAX


class TestMakeDnsName:
    def test_suffix_is_random(self) -> None:
        a = make_dns_name("nightly-train", fallback="train", max_total=TRAINING_NAME_MAX)
        b = make_dns_name("nightly-train", fallback="train", max_total=TRAINING_NAME_MAX)
        assert a != b
        assert a.startswith("nightly-train-")
        assert b.startswith("nightly-train-")

    def test_shape(self) -> None:
        name = make_dns_name(
            "nightly-train", fallback="train", max_total=TRAINING_NAME_MAX
        )
        assert _NAME_RE.match(name)
        prefix, suffix = name.rsplit("-", 1)
        assert prefix == "nightly-train"
        assert len(suffix) == 10

    def test_pure_chinese_falls_back(self) -> None:
        """清洗后为空 → 用 fallback, 不能吐出空前缀或裸后缀."""
        name = make_dns_name("实验一", fallback="train", max_total=TRAINING_NAME_MAX)
        assert name.startswith("train-")
        assert _NAME_RE.match(name)

    def test_no_double_hyphen_from_truncation(self) -> None:
        name = make_dns_name(
            "a" * 28 + "-b", fallback="train", max_total=TRAINING_NAME_MAX
        )
        assert "--" not in name


class TestSanitizeDnsLabel:
    """基线测试, 防将来误改 (6 个模块在用)."""

    def test_lowercase_and_replace(self) -> None:
        assert sanitize_dns_label("My Job!!") == "my-job"

    def test_collapse_and_strip_hyphens(self) -> None:
        assert sanitize_dns_label("--a___b--") == "a-b"

    def test_leading_digit_gets_fallback_prefix(self) -> None:
        assert sanitize_dns_label("1st-run", fallback="train") == "train-1st-run"

    def test_all_illegal_returns_fallback(self) -> None:
        assert sanitize_dns_label("实验一", fallback="train") == "train"
