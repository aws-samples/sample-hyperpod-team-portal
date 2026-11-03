"""健康检查: stdlib HTTP server 暴露 /healthz, 查心跳返回 200/503。
判据(health_status)与 server 解耦, 判据可纯函数测试。编排器(ECS/EKS)探活打它。
"""
from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from worker.heartbeat import Heartbeat
from worker.watchdog import WATCHDOG_THRESHOLD_SECONDS

log = logging.getLogger("worker.health")

HEALTH_PORT = 8080


def health_status(hb: Heartbeat, *, threshold: float) -> tuple[int, dict[str, Any]]:
    age = hb.seconds_since_progress()
    if age > threshold:
        return 503, {"status": "stalled", "age_seconds": round(age, 1)}
    return 200, {"status": "ok", "age_seconds": round(age, 1)}


def health_status_multi(
    hbs: list[Heartbeat], *, threshold: float
) -> tuple[int, dict[str, Any]]:
    """多路: 任一路心跳新鲜 → 200; 全部 stale → 503 (与看门狗一致)。"""
    ages = [round(hb.seconds_since_progress(), 1) for hb in hbs]
    if all(a > threshold for a in ages):
        return 503, {"status": "stalled", "ages": ages}
    return 200, {"status": "ok", "ages": ages}


def _make_handler(hbs: list[Heartbeat]):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/healthz":
                self.send_response(404)
                self.end_headers()
                return
            code, body = health_status_multi(hbs, threshold=WATCHDOG_THRESHOLD_SECONDS)
            log.debug("health.probe code=%d ages=%s", code, body["ages"])
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:  # 静音默认访问日志
            pass

    return _Handler


async def run_health_server(hbs: list[Heartbeat], *, port: int = HEALTH_PORT) -> None:
    """在线程池里跑阻塞式 HTTPServer (stdlib 无 async, 用 to_thread 不阻塞事件循环).

    hbs: 多路 informer 的 Heartbeat 列表; 任一路新鲜即 200, 全 stale 才 503。
    """
    server = HTTPServer(("0.0.0.0", port), _make_handler(hbs))
    log.info("health.server_start port=%d n_hb=%d", port, len(hbs))
    await asyncio.to_thread(server.serve_forever)
