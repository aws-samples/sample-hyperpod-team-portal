# app/modules/logs/domain/history_event.py
"""get_log_events 单行 message 解析 (纯函数).

CloudWatch get_log_events 的 event.message 是 Fluent Bit 双层 JSON envelope:
    {"time": "...", "stream": "stdout|stderr", "log": "<正文>", "kubernetes": {...}}
取 time / stream / log 三字段;解析失败降级 (原始串当 log)。
"""

from __future__ import annotations

import json


def parse_log_event(raw_message: str) -> dict[str, str]:
    """Fluent Bit envelope → {time, stream, log}. 失败降级不抛."""
    try:
        env = json.loads(raw_message)
        if isinstance(env, dict):
            stream = env.get("stream", "stdout")
            if stream not in ("stdout", "stderr"):
                stream = "stdout"
            return {
                "time": str(env.get("time", "")),
                "stream": stream,
                "log": str(env.get("log", "")).rstrip("\n"),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {"time": "", "stream": "stdout", "log": raw_message}
