"""Workspace GPU 利用率 7 天时序 · 纯逻辑 (PromQL 拼接 + 时间窗)。

口径 (2026-06-16): team 占用的 GPU 卡过去 N 天的利用率%。
- avg/max(DCGM_FI_DEV_GPU_UTIL{namespace="hyperpod-ns-xxx"})
- DCGM series 只在卡被某 pod 占用时才带 namespace 标签, 所以分母 = 当时
  实际占用卡数 (AMP 每时刻自带), 不依赖 AWS 配额 (配额无历史值)。
"""
from __future__ import annotations

from typing import Any

_GPU_UTIL_METRIC = "DCGM_FI_DEV_GPU_UTIL"
_STEP_SECONDS = 3600  # 1 点/小时 (7d = 168 点, AMP 可承受)


def build_gpu_util_queries(namespace: str) -> dict[str, str]:
    """返回 avg / max / count 三条按 namespace 过滤的 PromQL。

    - avg/max: 占用卡的利用率% (0-100)
    - count: 当时占用的 GPU 卡数 (带 namespace 标签的 series 数) — 占用率算不出
      (配额无历史), 但占用张数能从 DCGM 时序拿到。
    """
    selector = f'{_GPU_UTIL_METRIC}{{namespace="{namespace}"}}'
    return {
        "avg": f"avg({selector})",
        "max": f"max({selector})",
        "count": f"count({selector})",
    }


def gpu_util_time_window(*, days: int, now: float) -> dict[str, Any]:
    """算 range query 时间窗: [now - days*86400, now], step 1h。"""
    return {
        "start": now - days * 86400,
        "end": now,
        "step": _STEP_SECONDS,
    }
