"""Fluent Bit Insights event → LogLine 解析 (纯函数).

Insights 返回的每条事件是 ``list[{"field": str, "value": str}]``.
Fluent Bit envelope 示例::

    {
      "log": "Epoch 1 done\\n",
      "stream": "stdout",
      "kubernetes": {
        "pod_name": "hpj-e2e-38dceb-pods-0",
        "container_name": "trainer",
        "host": "hyperpod-i-0abc123",
        "labels": {"platform.hyperpod.io/training-job-id": "<uuid>"}
      }
    }

多行 Python 堆栈会被 Fluent Bit 合并成单条 event, 所以 ``log`` 字段
里的 ``\\n`` 保留即可, 不做二次拆分.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from app.modules.logs.api.schemas import LogLine


def parse_insights_event(ev: list[dict[str, Any]]) -> LogLine | None:
    """Parse one Insights event into a LogLine (``None`` if unparseable)."""
    by_field = {f["field"]: f["value"] for f in ev}
    ts_raw = by_field.get("@timestamp")
    msg_raw = by_field.get("@message", "")
    if not ts_raw:
        return None

    # `@timestamp` is `"2026-05-11 09:53:48.645"` UTC string; convert to ms.
    try:
        dt = _dt.datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S.%f").replace(
            tzinfo=_dt.timezone.utc
        )
        ts_ms = int(dt.timestamp() * 1000)
    except ValueError:
        return None

    # Fluent Bit envelope has the application payload under `log`.
    app_line = msg_raw
    try:
        parsed = json.loads(msg_raw)
        if isinstance(parsed, dict):
            app_line = parsed.get("log", msg_raw).rstrip("\n")
            stream = parsed.get("stream", "stdout")
            kube = parsed.get("kubernetes", {}) or {}
            return LogLine(
                timestamp_ms=ts_ms,
                message=app_line,
                stream=stream if stream in ("stdout", "stderr") else "stdout",
                pod=kube.get("pod_name"),
                container=kube.get("container_name"),
                node=kube.get("host"),
            )
    except (json.JSONDecodeError, TypeError):
        pass
    return LogLine(timestamp_ms=ts_ms, message=app_line)
