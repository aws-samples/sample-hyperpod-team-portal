"""看门狗: 周期检查心跳, 全路超阈值 sys.exit(1) (系统性故障, 编排器重启)。

只负责"全路 stale → 整进程退出"这一件事。单路 stale 的 cancel+重建由
supervisor 独自负责 (单一 owner, 避免两个协程同时操作 tasks list 产生竞态)。
判定(is_stalled/all_stalled)与动作(exit)解耦, 判定可纯函数测试。
"""
from __future__ import annotations

import asyncio
import logging
import sys

from worker.heartbeat import Heartbeat

log = logging.getLogger("worker.watchdog")

WATCHDOG_THRESHOLD_SECONDS = 900      # 全路阈值: 全 stale 超此数 → exit (健康检查也用此值)
WATCHDOG_CHECK_INTERVAL_SECONDS = 30


def is_stalled(hb: Heartbeat, *, threshold: float) -> bool:
    return hb.seconds_since_progress() > threshold


def all_stalled(hbs: list[Heartbeat], *, threshold: float) -> bool:
    return all(hb.seconds_since_progress() > threshold for hb in hbs)


async def run_watchdog_multi(
    hbs: list[Heartbeat],
    *,
    threshold: float = WATCHDOG_THRESHOLD_SECONDS,
    interval: float = WATCHDOG_CHECK_INTERVAL_SECONDS,
) -> None:
    """多路看门狗: 全部 stale → exit (任一路活着不重启, 避免单路问题误杀健康路)。

    单路 stale 不在此处理 — 交给 supervisor cancel+重建 (局部恢复)。
    """
    while True:
        await asyncio.sleep(interval)
        if all_stalled(hbs, threshold=threshold):
            ages = [round(hb.seconds_since_progress()) for hb in hbs]
            log.error(
                "watchdog.all_stalled ages=%s threshold=%.0fs, exiting(1) for restart",
                ages, threshold,
            )
            sys.exit(1)
        log.debug(
            "watchdog.check ages=%s threshold=%.0fs ok",
            [round(hb.seconds_since_progress()) for hb in hbs], threshold,
        )
