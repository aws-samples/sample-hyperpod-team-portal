# app/modules/logs/tests/test_history_event.py
"""Logs · get_log_events 单行解析 (纯函数) 单测."""

from __future__ import annotations

from app.modules.logs.domain.history_event import parse_log_event


def test_parse_normal_stdout() -> None:
    raw = (
        '{"time":"2026-06-04T03:17:42.034Z","stream":"stdout","_p":"F",'
        '"log":"Epoch 1 done","kubernetes":{"pod_name":"x"}}'
    )
    r = parse_log_event(raw)
    assert r["time"] == "2026-06-04T03:17:42.034Z"
    assert r["stream"] == "stdout"
    assert r["log"] == "Epoch 1 done"


def test_parse_stderr() -> None:
    raw = (
        '{"time":"2026-06-04T03:17:43.000Z","stream":"stderr",'
        '"log":"Traceback (most recent call last)"}'
    )
    r = parse_log_event(raw)
    assert r["stream"] == "stderr"
    assert r["log"].startswith("Traceback")


def test_parse_trailing_newline_stripped() -> None:
    raw = '{"time":"t","stream":"stdout","log":"line\\n"}'
    assert parse_log_event(raw)["log"] == "line"


def test_parse_garbage_degrades() -> None:
    # 非 JSON → 降级: 原始串当 log, stream 默认 stdout, time 空串
    r = parse_log_event("not json at all")
    assert r["log"] == "not json at all"
    assert r["stream"] == "stdout"
    assert r["time"] == ""
