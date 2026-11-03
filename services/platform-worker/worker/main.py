"""platform-worker 入口: 并发跑 informer + 看门狗 + supervisor + health server。

- informer: watch CR → 写 DDB (自管 rv 续传循环)。
- 看门狗: 全路心跳超阈值 sys.exit(1) → 编排器重启 (系统性故障)。
- supervisor: 单路 stale → cancel; 检测 task 结束 (被 cancel/异常) → 重建。
  cancel 与重建由 supervisor 独自负责 (单一 owner, 无竞态)。
- health: /healthz 探活 (编排器他杀, 与看门狗自杀双保险)。
异常分类: 瞬时(网络/5xx) 退避重试; 致命(bug/401/403) fail-fast 退出让编排器告警。
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from kubernetes_asyncio.client.exceptions import ApiException

from worker.health import run_health_server
from worker.heartbeat import Heartbeat
from worker.informers.devinstance import run_devinstance_informer
from worker.informers.inference import run_inference_informer
from worker.informers.training import run_training_informer
from worker.watchdog import run_watchdog_multi

# 多路 informer (每类 CR 一路独立长连接 + 独立心跳): 训练 + 推理 + 开发机。
_INFORMER_RUNNERS = (
    run_training_informer,
    run_inference_informer,
    run_devinstance_informer,
)

_SUPERVISOR_CHECK_INTERVAL = 5  # supervisor 检测 task done / 单路 stale 的间隔
# 单路 stale 阈值: 某一路超此秒数未刷心跳 → supervisor cancel 它 (随后重建)。
# 必须 < 看门狗全路阈值 (900s), 让局部自愈先于整进程重启生效。
# 正常 watch 周期 300s, 超 2 个周期 (600s) 没进展即判该路卡死。
_SINGLE_STALL_THRESHOLD_SECONDS = 600


def resolve_log_level() -> int:
    """LOG_LEVEL 环境变量解析为 logging 级别。默认 INFO; 设 DEBUG 出全量详细日志。
    非法值回退 INFO (不让配置错误把日志关掉)。"""
    name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(name)
    return level if isinstance(level, int) else logging.INFO


logging.basicConfig(
    level=resolve_log_level(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("worker.main")

_TRANSIENT_BACKOFF_SECONDS = 5


def is_fatal(exc: BaseException) -> bool:
    """致命错误 fail-fast (让编排器重启+告警); 瞬时错误退避重试。"""
    if isinstance(exc, ApiException):
        return exc.status in (401, 403)  # 鉴权失败 = 配置/权限问题, 重试无用
    # 编程错误(bug) 致命; 网络类瞬时
    return isinstance(exc, (TypeError, KeyError, AttributeError, ValueError, ImportError))


async def _run_informer_forever(runner, hb: Heartbeat) -> None:
    while True:
        try:
            await runner(hb)
            log.info("%s returned normally, restarting", runner.__name__)
        except asyncio.CancelledError:
            # log 后必须 re-raise: 让 CancelledError 传播到 task 顶层, 使
            # task.cancelled()==True (supervisor 阶段2 据此跳过 exception() 直接重建)。
            # 吞掉改 return 会让 task 变"正常完成", cancelled() 恒 False, 那条分支成
            # 死代码, 且 informer 失去响应取消的能力 (优雅关闭会埋雷)。
            log.warning("%s cancelled (stale), will be rebuilt by supervisor", runner.__name__)
            raise
        except Exception as exc:  # noqa: BLE001
            if is_fatal(exc):
                log.error("%s fatal error, exiting for restart: %s", runner.__name__, exc)
                raise
            log.error("%s transient error, retry in %ds: %s",
                      runner.__name__, _TRANSIENT_BACKOFF_SECONDS, exc)
            await asyncio.sleep(_TRANSIENT_BACKOFF_SECONDS)


def _create_informer_task(runner, hb: Heartbeat) -> asyncio.Task:
    """创建一个 informer task。

    致命异常不在此处 callback 退出 — 统一由 supervisor 检测 (单一退出路径)。
    supervisor 持有 task 引用且每轮调用 .exception(), 故不会触发
    "Task exception was never retrieved" 警告。
    """
    return asyncio.create_task(
        _run_informer_forever(runner, hb),
        name=f"informer-{runner.__name__}",
    )


async def _supervisor(
    runners: tuple,
    hbs: list[Heartbeat],
    tasks: list[asyncio.Task],
) -> None:
    """单一 owner: 单路 stale → cancel; task 结束 (被 cancel/异常) → 重建。

    只有 supervisor 写 tasks list, 看门狗不碰, 故无竞态。两阶段天然解耦:
    本轮 cancel 只发请求 (task 还没 done), 下一轮检测到 done 才重建 —
    cancel 未生效前不会重建, 也不会有人 cancel 刚重建的新 task。
    致命异常 → sys.exit(1) 让编排器重启 (重试无用)。
    """
    while True:
        await asyncio.sleep(_SUPERVISOR_CHECK_INTERVAL)
        for i, (runner, hb) in enumerate(zip(runners, hbs)):
            task = tasks[i]
            # 阶段1: 单路 stale 且还活着 → cancel (本轮不重建, 等下轮它真 done)
            if not task.done():
                if hb.seconds_since_progress() > _SINGLE_STALL_THRESHOLD_SECONDS:
                    log.warning(
                        "supervisor: task %d (%s) stale age=%.0fs, cancelling",
                        i, runner.__name__, hb.seconds_since_progress(),
                    )
                    task.cancel()
                continue
            # 阶段2: task 已结束 (被 cancel 或异常退出) → 重建
            exc = task.exception() if not task.cancelled() else None
            if exc is not None and is_fatal(exc):
                log.error("supervisor: task %d fatal exception, exiting: %s", i, exc)
                sys.exit(1)
            # warning 而非 info: 正常 informer 永在 while True 内不退出, 走到重建
            # 即说明该路出过异常 (stale 被 cancel / runner 返回), 升级日志级别供告警抓取。
            log.warning("supervisor: task %d (%s) done, rebuilding", i, runner.__name__)
            hb.mark_progress()  # 重建时刷心跳, 给新 task 一个完整 stale 窗口
            tasks[i] = _create_informer_task(runner, hb)


async def main() -> None:
    log.info("platform-worker starting (%d informers)", len(_INFORMER_RUNNERS))
    # 每路 informer 一个独立 Heartbeat
    hbs = [Heartbeat() for _ in _INFORMER_RUNNERS]
    for hb in hbs:
        hb.mark_progress()  # 启动即标记, 避免冷启动期间被看门狗误判

    # 创建 informer tasks (supervisor 持有引用, 用于 cancel + 检测 done + 重建)
    inf_tasks: list[asyncio.Task] = [
        _create_informer_task(runner, hb)
        for runner, hb in zip(_INFORMER_RUNNERS, hbs)
    ]

    await asyncio.gather(
        run_watchdog_multi(hbs),
        _supervisor(_INFORMER_RUNNERS, hbs, inf_tasks),
        run_health_server(hbs),
    )


if __name__ == "__main__":
    asyncio.run(main())
