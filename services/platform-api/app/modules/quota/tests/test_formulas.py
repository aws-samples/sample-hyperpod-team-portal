"""domain/formulas.py 的纯函数单测."""

from __future__ import annotations

import pytest

from app.modules.quota.domain.formulas import (
    ACCELERATOR_RESOURCE_KEYS,
    aggregate_totals,
    parse_cpu_cores,
    parse_int_count,
    parse_memory_gib,
)


class TestParseCpuCores:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2", 2.0),
            ("2000m", 2.0),
            ("500m", 0.5),
            (2, 2.0),
            (2.5, 2.5),
            (None, 0.0),
            ("", 0.0),
            ("garbage", 0.0),
            ("abcm", 0.0),
            ("   3  ", 3.0),  # trim
        ],
    )
    def test_parses(self, raw: object, expected: float) -> None:
        assert parse_cpu_cores(raw) == expected  # type: ignore[arg-type]


class TestParseMemoryGib:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("8Gi", 8.0),
            ("8192Mi", 8.0),
            ("8589934592", 8.0),    # bytes
            ("1Ti", 1024.0),
            ("1024Ki", 1024 / 1024 / 1024),  # 小量级不重要, 只要不 raise
            (None, 0.0),
            ("", 0.0),
            ("badGi", 0.0),
        ],
    )
    def test_parses(self, raw: object, expected: float) -> None:
        got = parse_memory_gib(raw)  # type: ignore[arg-type]
        assert abs(got - expected) < 1e-6


class TestParseIntCount:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("8", 8),
            ("8000m", 8),
            (8, 8),
            (8.9, 8),
            (None, 0),
            ("", 0),
            ("garbage", 0),
        ],
    )
    def test_parses(self, raw: object, expected: int) -> None:
        assert parse_int_count(raw) == expected  # type: ignore[arg-type]


class TestAggregateTotals:
    def test_empty(self) -> None:
        assert aggregate_totals([]) == (0, 0.0, 0.0)

    def test_single_row(self) -> None:
        # count=2, accel=8, vcpu=96.0, mem=1152.0
        result = aggregate_totals([(2, 8, 96.0, 1152.0)])
        assert result == (16, 192.0, 2304.0)

    def test_multi_row(self) -> None:
        rows = [
            (2, 8, 96.0, 1152.0),  # ml.p4d
            (3, 4, 48.0, 192.0),   # ml.g5
        ]
        accel, vcpu, mem = aggregate_totals(rows)
        assert accel == 2 * 8 + 3 * 4  # 28
        assert vcpu == round(2 * 96.0 + 3 * 48.0, 2)  # 336.0
        assert mem == round(2 * 1152.0 + 3 * 192.0, 2)  # 2880.0

    def test_rounding(self) -> None:
        # 浮点精度误差应被 round(., 2) 修掉
        rows = [(1, 0, 0.1, 0.2), (1, 0, 0.2, 0.1)]
        _, vcpu, mem = aggregate_totals(rows)
        assert vcpu == 0.30
        assert mem == 0.30


def test_accelerator_keys_includes_gpu_and_neuron() -> None:
    """Kueue status 里识别 GPU 与 Neuron 两种加速器."""
    assert "nvidia.com/gpu" in ACCELERATOR_RESOURCE_KEYS
    assert "aws.amazon.com/neurondevice" in ACCELERATOR_RESOURCE_KEYS
