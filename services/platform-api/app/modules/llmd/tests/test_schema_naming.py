"""LlmdCreate 任务名 / 显示名校验 (上限 20 的由来见 core/naming.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.naming import LLMD_NAME_MAX, make_dns_name
from app.modules.llmd.api.schemas import LlmdCreate

_BASE = {
    "model_source_type": "fsx",
    "model_pvc": "pvc-ws-fsx-team-a-data-rw",
    "launch_script": "exec python3 -m sglang.launch_server",
    "gpu_instance_type": "ml.g6.12xlarge",
    "gateway_instance_type": "ml.g6.12xlarge",
}


def _make(**overrides) -> LlmdCreate:
    base = dict(_BASE, display_name="llmd-svc")
    base.update(overrides)
    return LlmdCreate.model_validate(base)


def _msg(**overrides) -> str:
    with pytest.raises(ValidationError) as ei:
        _make(**overrides)
    return "; ".join(e["msg"] for e in ei.value.errors())


class TestDisplayName:
    def test_normal_accepted(self) -> None:
        assert _make().display_name == "llmd-svc"

    def test_max_length_20_accepted(self) -> None:
        assert _make(display_name="a" * 20).display_name == "a" * 20

    def test_21_chars_rejected_with_actual_length(self) -> None:
        assert "实际 21" in _msg(display_name="a" * 21)

    def test_too_short_rejected(self) -> None:
        assert "3-20" in _msg(display_name="ab")

    def test_chinese_rejected_with_plain_message(self) -> None:
        assert "中文" in _msg(display_name="多机推理")

    def test_fullwidth_rejected(self) -> None:
        # 全角字符用 chr() 构造: 留在源码里的字面量看着和半角一样, 谁都分不出
        assert "中文" in _msg(display_name="llmd" + chr(0xFF13))

    def test_tab_reported_as_charset(self) -> None:
        """制表符是 ASCII 但不可打印, 报的应是字符集问题。"""
        assert "可打印" in _msg(display_name="llmd\tx")

    def test_uppercase_rejected_by_pattern(self) -> None:
        assert _msg(display_name="Llmd")

    def test_trailing_hyphen_rejected(self) -> None:
        assert _msg(display_name="llmd-")


class TestNameRejected:
    def test_client_supplied_name_rejected(self) -> None:
        assert "由后端" in _msg(name="my-own-name")

    def test_name_absent_is_ok(self) -> None:
        assert _make().name is None


class TestDerivedNameFitsKueueLabel:
    def test_max_display_name_lands_on_limit(self) -> None:
        name = make_dns_name("a" * 20, fallback="llmd", max_total=LLMD_NAME_MAX)
        assert len(name) == LLMD_NAME_MAX == 31

    def test_label_value_stays_within_63_at_worst_replicas(self) -> None:
        """label 值 = 29 + len(name) + group-index 位数; replicas 上限 256 时占 3 位。"""
        name = make_dns_name("a" * 20, fallback="llmd", max_total=LLMD_NAME_MAX)
        assert 29 + len(name) + 3 <= 63
