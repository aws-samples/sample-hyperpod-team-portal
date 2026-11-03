"""共享心跳状态: worker 每次取得进展(watch 周期返回/收到事件)调 mark_progress()。
看门狗和 /healthz 都读 seconds_since_progress() 判活。用 monotonic 避免系统时钟跳变。
"""
from __future__ import annotations

import time

_NEVER = -1.0e12  # 初始 sentinel: 从未进展 → age 极大


class Heartbeat:
    def __init__(self) -> None:
        self._last = _NEVER

    def mark_progress(self) -> None:
        self._last = time.monotonic()

    def seconds_since_progress(self) -> float:
        return time.monotonic() - self._last
