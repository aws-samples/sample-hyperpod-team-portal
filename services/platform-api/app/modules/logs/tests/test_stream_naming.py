# app/modules/logs/tests/test_stream_naming.py
"""Logs · stream 名解析 (纯函数) 单测."""

from __future__ import annotations

from app.modules.logs.domain.stream_naming import (
    assign_seq,
    parse_stream_name,
    trainer_stream_prefix,
)


def test_trainer_stream_prefix() -> None:
    assert (
        trainer_stream_prefix("ddp-smoke-03-f7b6ee")
        == "FluentBit/kube.var.log.containers.ddp-smoke-03-f7b6ee-pods-"
    )


def test_parse_trainer_stream() -> None:
    s = (
        "FluentBit/kube.var.log.containers."
        "ddp-smoke-03-f7b6ee-pods-cb7f4d8d-4b8s8_"
        "hyperpod-ns-demo_trainer-72cccd38ab.log"
    )
    r = parse_stream_name(s)
    assert r is not None
    assert r["pod_name"] == "ddp-smoke-03-f7b6ee-pods-cb7f4d8d-4b8s8"
    assert r["pod_short"] == "4b8s8"
    assert r["container"] == "trainer"
    assert r["container_id"] == "72cccd38ab"


def test_parse_non_trainer_returns_none() -> None:
    # pod-manager / code-sync 容器不是训练日志
    s = (
        "FluentBit/kube.var.log.containers."
        "ddp-smoke-03-f7b6ee-podmanagers-0_aws-hyperpod_"
        "pod-manager-bca9bff9.log"
    )
    assert parse_stream_name(s) is None


def test_parse_garbage_returns_none() -> None:
    assert parse_stream_name("totally-not-a-fluentbit-stream") is None


def test_parse_empty_container_id_returns_none() -> None:
    s = (
        "FluentBit/kube.var.log.containers."
        "ddp-smoke-03-f7b6ee-pods-cb7f4d8d-4b8s8_"
        "hyperpod-ns-demo_trainer-.log"
    )
    assert parse_stream_name(s) is None


def test_assign_seq_single_pod_multi_stream() -> None:
    # 同一 pod 重启 2 次 (2 个 stream), 按 first_ts 升序编号 #1 #2
    streams = [
        {"pod_short": "4b8s8", "first_ts": 200, "last_ts": 300, "stream_name": "B"},
        {"pod_short": "4b8s8", "first_ts": 100, "last_ts": 150, "stream_name": "A"},
    ]
    out = assign_seq(streams)
    by_name = {s["stream_name"]: s["seq"] for s in out}
    assert by_name["A"] == 1  # 更早的是 #1
    assert by_name["B"] == 2


def test_assign_seq_multi_pod_independent() -> None:
    # 不同 pod 各自从 #1 起编
    streams = [
        {"pod_short": "aaa", "first_ts": 100, "last_ts": 150, "stream_name": "A"},
        {"pod_short": "bbb", "first_ts": 120, "last_ts": 160, "stream_name": "B"},
    ]
    out = assign_seq(streams)
    by_name = {s["stream_name"]: s["seq"] for s in out}
    assert by_name["A"] == 1
    assert by_name["B"] == 1
