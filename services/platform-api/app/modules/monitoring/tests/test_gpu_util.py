"""workspace GPU 利用率 7 天时序 · 纯逻辑测试 (PromQL 拼接 + 时间窗)。

设计 (2026-06-16): 管理员看 team 占用 GPU 的 7 天利用率%。
- 口径: avg/max(DCGM_FI_DEV_GPU_UTIL{namespace=...}), 分母是 AMP 每时刻自带的
  "当时占用卡数", 不依赖 AWS 配额 (配额无历史)。
- 鉴权 assert_ws_admin 在端点层, 这里只测纯拼接逻辑。
"""
from __future__ import annotations

from app.modules.monitoring.domain.gpu_util import (
    build_gpu_util_queries,
    gpu_util_time_window,
)


def test_build_queries_filters_by_namespace():
    q = build_gpu_util_queries("hyperpod-ns-team-a")
    sel = 'DCGM_FI_DEV_GPU_UTIL{namespace="hyperpod-ns-team-a"}'
    assert q["avg"] == f"avg({sel})"
    assert q["max"] == f"max({sel})"
    # count = 当时占用的 GPU 卡数 (有 namespace 标签的 series 数)
    assert q["count"] == f"count({sel})"


def test_time_window_7d_hourly_step():
    now = 1_000_000.0
    w = gpu_util_time_window(days=7, now=now)
    assert w["end"] == 1_000_000.0
    assert w["start"] == 1_000_000.0 - 7 * 86400
    assert w["step"] == 3600


def test_time_window_custom_days():
    now = 2_000_000.0
    w = gpu_util_time_window(days=1, now=now)
    assert w["start"] == 2_000_000.0 - 86400
    assert w["step"] == 3600
