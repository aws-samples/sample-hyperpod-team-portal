import pytest

from app.modules.fsx_quota.orchestration.quota import (
    FsxQuotaError,
    check_quota_sum_ok,
)


def test_quota_sum_ok_under():
    # 100 + 200 + 300 = 600 < 1200 → 放行
    check_quota_sum_ok(100, [200, 300], 1200)


def test_quota_sum_ok_exactly_at_total():
    # 700 + 500 = 1200 == 总容量 → 允许 (等于不算超)
    check_quota_sum_ok(700, [500], 1200)


def test_quota_sum_over_raises():
    # 800 + 500 = 1300 > 1200 → 拒
    with pytest.raises(FsxQuotaError):
        check_quota_sum_ok(800, [500], 1200)


def test_quota_sum_none_total_skips():
    # 拿不到总容量 (None) → 跳过校验, 不阻断
    check_quota_sum_ok(9999, [], None)
