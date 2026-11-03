# app/modules/logs/tests/test_history_orch.py
"""Logs · 历史日志 orchestration 单测 (mock adapter + crud)."""

from __future__ import annotations

import pytest

from app.modules.logs.orchestration import history


@pytest.mark.asyncio
async def test_list_streams_filters_trainer_and_assigns_seq(monkeypatch) -> None:
    # 两条 trainer (同 pod 重启) + 一条 pod-manager (应被过滤)
    trainer_a = (
        "FluentBit/kube.var.log.containers."
        "job-x-pods-h1-p1_ns_trainer-c1.log"
    )
    trainer_b = (
        "FluentBit/kube.var.log.containers."
        "job-x-pods-h1-p1_ns_trainer-c2.log"
    )
    podmgr = (
        "FluentBit/kube.var.log.containers."
        "job-x-podmanagers-0_aws-hyperpod_pod-manager-c3.log"
    )

    async def fake_describe(*, log_group, prefix):
        return [
            {"logStreamName": trainer_b, "firstEventTimestamp": 200,
             "lastEventTimestamp": 300},
            {"logStreamName": trainer_a, "firstEventTimestamp": 100,
             "lastEventTimestamp": 150},
            {"logStreamName": podmgr, "firstEventTimestamp": 50,
             "lastEventTimestamp": 60},
        ]

    monkeypatch.setattr(history.cw, "describe_log_streams_by_prefix", fake_describe)

    streams = await history.list_streams(
        k8s_job_name="job-x", cluster_tag="ct", cluster_arn="arn:.../cid"
    )
    # pod-manager 被过滤, 只剩 2 条 trainer
    assert len(streams) == 2
    # seq: 更早 (first_ts=100) 的是 #1
    by_name = {s.stream_name: s.seq for s in streams}
    assert by_name[trainer_a] == 1
    assert by_name[trainer_b] == 2
    # 完整 pod_name 透出 (前端下拉显示 + 抽屉跳转匹配用)
    assert all(s.pod_name == "job-x-pods-h1-p1" for s in streams)


@pytest.mark.asyncio
async def test_fetch_page_parses_lines(monkeypatch) -> None:
    # 单页即到头: 首批返回 2 行 + backward 指针 b; 跟随 b 时 token 收敛 (== b) → 停。
    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        if next_token is None:
            return {
                "events": [
                    {"timestamp": 1, "message":
                     '{"time":"t1","stream":"stdout","log":"hello"}'},
                    {"timestamp": 2, "message":
                     '{"time":"t2","stream":"stderr","log":"boom"}'},
                ],
                "next_forward_token": "f",
                "next_backward_token": "b",
            }
        # 跟随 b → 到头 (空 + token 收敛)
        return {"events": [], "next_forward_token": "f", "next_backward_token": "b"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    # 首屏 (token=None): 定位最新, 返回双向 token
    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        stream="job-x-pods...", token=None,
    )
    assert [l.log for l in page.lines] == ["hello", "boom"]
    assert page.lines[1].stream == "stderr"
    assert page.mode == "browse"
    # 首屏同时给两个方向的 token: forward(下滑追更新, 首批最新端) + backward(末批最旧端)
    assert page.forward_token == "f"
    assert page.backward_token == "b"


def _ev(ts: int, log: str) -> dict:
    return {"timestamp": ts, "message":
            f'{{"time":"t{ts}","stream":"stdout","log":"{log}"}}'}


@pytest.mark.asyncio
async def test_fetch_page_accumulates_backward_to_limit(monkeypatch) -> None:
    """首屏 anchor=newest: 单页不足 limit 时沿 backward 累积, 行序恒 old→new,
    forward_token=首批(最新), backward_token=末批(最旧)。"""
    # 模拟每页 2 行、单页到 1MB 上限的 CloudWatch: 越翻越旧。
    # 批次 (backward 方向, 每批更旧): 先返最新的 [5,6], 再 [3,4], 再 [1,2] 到头。
    batches = [
        {"events": [_ev(5, "e5"), _ev(6, "e6")],
         "next_forward_token": "F", "next_backward_token": "b1"},
        {"events": [_ev(3, "e3"), _ev(4, "e4")],
         "next_forward_token": "f1", "next_backward_token": "b2"},
        {"events": [_ev(1, "e1"), _ev(2, "e2")],
         "next_forward_token": "f2", "next_backward_token": "b3"},
        # 到头: token 不再前进
        {"events": [], "next_forward_token": "f2", "next_backward_token": "b3"},
    ]
    calls = {"n": 0, "tokens": []}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        calls["tokens"].append(next_token)
        i = calls["n"]
        calls["n"] += 1
        return batches[min(i, len(batches) - 1)]

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    # 要 6 行 (limit=6), 单页 2 行 → 需累积 3 批
    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        stream="s", token=None, anchor="newest", limit=6,
    )
    # 行序 old→new
    assert [l.log for l in page.lines] == ["e1", "e2", "e3", "e4", "e5", "e6"]
    # forward_token = 首批(最新)的; backward_token = 末批(最旧)的
    assert page.forward_token == "F"
    assert page.backward_token == "b3"
    assert page.mode == "browse"
    # 沿 backward 翻: 首次 token=None, 之后跟 next_backward_token
    assert calls["tokens"][:3] == [None, "b1", "b2"]


@pytest.mark.asyncio
async def test_fetch_page_accumulation_stops_at_limit(monkeypatch) -> None:
    """攒够 limit 即停, 不多翻。"""
    calls = {"n": 0}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        n = calls["n"]
        calls["n"] += 1
        # 每批 2 行, 无限可翻
        base = 100 - n * 2
        return {"events": [_ev(base, f"x{base}"), _ev(base + 1, f"x{base+1}")],
                "next_forward_token": f"F{n}", "next_backward_token": f"b{n}"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    # limit=3: 第1批2行不够, 第2批到4行≥3 → 停; 共 2 次调用
    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        stream="s", token=None, anchor="newest", limit=3,
    )
    assert len(page.lines) >= 3
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_fetch_page_accumulation_capped_by_max_pages(monkeypatch) -> None:
    """超大 stream + 大 limit: 最多翻 _ACCUM_MAX_PAGES 页就返回。"""
    calls = {"n": 0}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        n = calls["n"]
        calls["n"] += 1
        base = 100000 - n * 2
        return {"events": [_ev(base, "y"), _ev(base + 1, "y")],
                "next_forward_token": f"F{n}", "next_backward_token": f"b{n}"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    # limit 巨大, 每页 2 行永远攒不够 → 撞 _ACCUM_MAX_PAGES 上限停
    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        stream="s", token=None, anchor="newest", limit=100000,
    )
    assert calls["n"] == history._ACCUM_MAX_PAGES
    assert len(page.lines) == history._ACCUM_MAX_PAGES * 2


@pytest.mark.asyncio
async def test_fetch_page_default_single_call_when_page_fits(monkeypatch) -> None:
    """默认 limit(500): 单页就返回够多行时不累积 (仅 1 次调用)。"""
    calls = {"n": 0}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        calls["n"] += 1
        # 单页直接返回 500 行 (= 默认 target), 一次到位
        evs = [_ev(i, "z") for i in range(1, history._FIRST_PAGE_LIMIT + 1)]
        return {"events": evs, "next_forward_token": "F", "next_backward_token": "b"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid",
        stream="s", token=None, anchor="newest",  # 不传 limit → 默认 500
    )
    assert calls["n"] == 1
    assert len(page.lines) == history._FIRST_PAGE_LIMIT


@pytest.mark.asyncio
async def test_iter_all_lines_paginates_until_token_stops(monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "events": [{"timestamp": 1, "message":
                            '{"time":"t1","stream":"stdout","log":"a"}'}],
                "next_forward_token": "f1",
                "next_backward_token": "b1",
            }
        if calls["n"] == 2:
            return {
                "events": [{"timestamp": 2, "message":
                            '{"time":"t2","stream":"stdout","log":"b"}'}],
                "next_forward_token": "f2",
                "next_backward_token": "b2",
            }
        # 第 3 次: token 不再前进 (== 上次), 应停止
        return {
            "events": [{"timestamp": 3, "message":
                        '{"time":"t3","stream":"stdout","log":"c"}'}],
            "next_forward_token": "f2",
            "next_backward_token": "b2",
        }

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    out = []
    async for chunk in history.iter_all_lines(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s"
    ):
        out.append(chunk)

    # 3 页都 yield (第 3 页 yield 后才发现 token 没前进而停)
    assert out == ["t1 [stdout] a\n", "t2 [stdout] b\n", "t3 [stdout] c\n"]
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_iter_all_lines_stops_on_empty(monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "events": [{"timestamp": 1, "message":
                            '{"time":"t1","stream":"stdout","log":"a"}'}],
                "next_forward_token": "f1",
                "next_backward_token": "b1",
            }
        return {"events": [], "next_forward_token": "f1", "next_backward_token": "b1"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    out = [c async for c in history.iter_all_lines(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s")]
    assert out == ["t1 [stdout] a\n"]


@pytest.mark.asyncio
async def test_list_streams_sorted_newest_first(monkeypatch) -> None:
    older = (
        "FluentBit/kube.var.log.containers."
        "job-x-pods-h1-p1_ns_trainer-c1.log"
    )
    newer = (
        "FluentBit/kube.var.log.containers."
        "job-x-pods-h2-p2_ns_trainer-c2.log"
    )

    async def fake_describe(*, log_group, prefix):
        return [
            {"logStreamName": older, "firstEventTimestamp": 100,
             "lastEventTimestamp": 150},
            {"logStreamName": newer, "firstEventTimestamp": 200,
             "lastEventTimestamp": 300},
        ]

    monkeypatch.setattr(history.cw, "describe_log_streams_by_prefix", fake_describe)

    streams = await history.list_streams(
        k8s_job_name="job-x", cluster_tag="ct", cluster_arn="arn:.../cid"
    )
    # last_ts 倒序: newer (300) 在前
    assert streams[0].stream_name == newer
    assert streams[0].last_ts >= streams[1].last_ts


@pytest.mark.asyncio
async def test_list_ray_streams_driver_numbered_independently(monkeypatch) -> None:
    # 同一 head pod: 1 条常规 ray-head + 2 条 driver-log-tailer (重启产两条)。
    # driver 应独立编号 (#1/#2), 不与常规 ray-head 混进同一序列。
    rc = "bob-ray-01-6jhqrk9o07-5czbk"
    head = f"{rc}-head-7znnx"
    p = "FluentBit/kube.var.log.containers."
    ray_head = f"{p}{head}_ns_ray-head-c1.log"
    driver_a = f"{p}{head}_ns_driver-log-tailer-c2.log"
    driver_b = f"{p}{head}_ns_driver-log-tailer-c3.log"

    async def fake_describe(*, log_group, prefix):
        return [
            {"logStreamName": driver_b, "firstEventTimestamp": 300,
             "lastEventTimestamp": 350},
            {"logStreamName": ray_head, "firstEventTimestamp": 100,
             "lastEventTimestamp": 400},
            {"logStreamName": driver_a, "firstEventTimestamp": 200,
             "lastEventTimestamp": 250},
        ]

    monkeypatch.setattr(history.cw, "describe_log_streams_by_prefix", fake_describe)

    streams = await history.list_ray_streams(
        ray_cluster_name=rc, cluster_tag="ct", cluster_arn="arn:.../cid"
    )
    seq = {s.stream_name: s.seq for s in streams}
    # 常规 ray-head 独立编号 #1
    assert seq[ray_head] == 1
    # driver 独立编号: 更早 (first_ts=200) 的是 #1, 更晚的是 #2
    assert seq[driver_a] == 1
    assert seq[driver_b] == 2


@pytest.mark.asyncio
async def test_fetch_page_follows_empty_first_response(monkeypatch) -> None:
    # CloudWatch 从末尾首次返回空 events + 指针 token, 需跟随 backward token 才见数据。
    # fetch_page 应自动跟随, 首屏直接返回非空 lines (用户无需手点"加载更早")。
    calls = {"n": 0}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # 首次 (token=None): 空 events, 给一个 backward 指针
            assert next_token is None
            return {"events": [], "next_forward_token": "f0",
                    "next_backward_token": "b1"}
        if calls["n"] == 2:
            # 跟随 b1: 返回真实数据 (仅 1 行, 该 stream 到此为止)
            assert next_token == "b1"
            return {
                "events": [{"timestamp": 1, "message":
                            '{"time":"t1","stream":"stdout","log":"real"}'}],
                "next_forward_token": "f1",
                "next_backward_token": "b2",
            }
        # 跟随 b2: 到头 (空 + token 收敛)
        assert next_token == "b2"
        return {"events": [], "next_forward_token": "f1", "next_backward_token": "b2"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s", token=None
    )
    assert [l.log for l in page.lines] == ["real"]
    assert page.backward_token == "b2"  # 末批(最旧端)的 backward token
    assert page.forward_token == "f0"   # 首批(最新端)的 forward token
    assert calls["n"] == 3  # 跟随空页 + 取数据 + 探到头


@pytest.mark.asyncio
async def test_fetch_page_empty_stream_stops(monkeypatch) -> None:
    # 真空 stream: 首屏 backward token 不变 → 停止, 返回空 (不死循环)。
    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        return {"events": [], "next_forward_token": "f", "next_backward_token": "bsame"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s", token=None
    )
    assert page.lines == []


@pytest.mark.asyncio
async def test_fetch_page_anchor_oldest_starts_from_head(monkeypatch) -> None:
    # anchor=oldest (旧→新首屏): 应 startFromHead=True 定位最早, 返回双向 token。
    seen = {}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        seen["head"] = start_from_head
        if next_token is None:
            return {
                "events": [{"timestamp": 1, "message":
                            '{"time":"t1","stream":"stdout","log":"oldest"}'}],
                "next_forward_token": "f", "next_backward_token": "b",
            }
        # oldest 沿 forward 累积; 跟随 f → 到头 (空 + 收敛)
        return {"events": [], "next_forward_token": "f", "next_backward_token": "b"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s",
        token=None, anchor="oldest",
    )
    assert seen["head"] is True  # 定位最早
    assert [l.log for l in page.lines] == ["oldest"]
    assert page.forward_token == "f" and page.backward_token == "b"


@pytest.mark.asyncio
async def test_fetch_page_load_forward_uses_head_and_forward_token(monkeypatch) -> None:
    # load_dir=forward (下滑追更新): 带 token, start_from_head=True, 返回 forward_token。
    seen = {}

    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        seen["head"] = start_from_head
        if next_token == "f1":  # 首次带入的 token
            seen["token_in"] = next_token
            return {
                "events": [{"timestamp": 1, "message":
                            '{"time":"t1","stream":"stdout","log":"newer"}'}],
                "next_forward_token": "f2",
                "next_backward_token": "b2",
            }
        # 跟随 f2 → 到头 (空 + 收敛)
        return {"events": [], "next_forward_token": "f2", "next_backward_token": "b2"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s",
        token="f1", load_dir="forward",
    )
    assert seen["head"] is True
    assert seen["token_in"] == "f1"
    assert [l.log for l in page.lines] == ["newer"]
    assert page.forward_token == "f2"  # 刷新后的 forward token, 继续下滑


@pytest.mark.asyncio
async def test_fetch_page_load_backward_uses_backward_token(monkeypatch) -> None:
    # load_dir=backward (上滑看更早): 带 token, 返回 backward_token。
    async def fake_get(*, log_group, stream, start_from_head, next_token, limit,
                       start_ms=None, end_ms=None):
        if next_token == "b1":  # 首次带入的 token
            return {
                "events": [{"timestamp": 1, "message":
                            '{"time":"t1","stream":"stdout","log":"older"}'}],
                "next_forward_token": "f2",
                "next_backward_token": "b2",
            }
        # 跟随 b2 → 到头 (空 + 收敛)
        return {"events": [], "next_forward_token": "f2", "next_backward_token": "b2"}

    monkeypatch.setattr(history.cw, "get_log_events", fake_get)

    page = await history.fetch_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s",
        token="b1", load_dir="backward",
    )
    assert [l.log for l in page.lines] == ["older"]
    assert page.backward_token == "b2"


# ===== search_page (FilterLogEvents, 恒旧→新单向) =====


@pytest.mark.asyncio
async def test_search_page_builds_pattern_and_parses(monkeypatch) -> None:
    seen = {}

    async def fake_filter(*, log_group, stream, filter_pattern, start_ms,
                          end_ms, next_token, limit):
        seen.update(
            filter_pattern=filter_pattern, start_ms=start_ms,
            end_ms=end_ms, token=next_token,
        )
        return {
            "events": [
                {"timestamp": 1, "message":
                 '{"time":"t1","stream":"stdout","log":"hit ERROR here"}'},
            ],
            "next_token": None,  # 到最新
        }

    monkeypatch.setattr(history.cw, "filter_log_events", fake_filter)

    page = await history.search_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s",
        query="ERROR", is_regex=False, start_ms=100, end_ms=200, token=None,
    )
    assert seen["filter_pattern"] == '{ $.log = "*ERROR*" }'
    assert seen["start_ms"] == 100 and seen["end_ms"] == 200
    assert [l.log for l in page.lines] == ["hit ERROR here"]
    assert page.mode == "search"
    assert page.next_token is None  # 到最新


@pytest.mark.asyncio
async def test_search_page_accumulates_until_target(monkeypatch) -> None:
    # 单页少量, 后端应翻页累积直到 target 或 token 耗尽。
    monkeypatch.setattr(history, "_FILTER_TARGET_LINES", 3)
    monkeypatch.setattr(history, "_FILTER_MAX_PAGES", 10)
    calls = {"n": 0}

    async def fake_filter(*, log_group, stream, filter_pattern, start_ms,
                          end_ms, next_token, limit):
        calls["n"] += 1
        if calls["n"] < 3:
            return {
                "events": [{"timestamp": calls["n"], "message":
                            f'{{"time":"t{calls["n"]}","stream":"stdout","log":"L{calls["n"]}"}}'}],
                "next_token": f"tok{calls['n']}",
            }
        return {
            "events": [{"timestamp": 3, "message":
                        '{"time":"t3","stream":"stdout","log":"L3"}'}],
            "next_token": "tok3",
        }

    monkeypatch.setattr(history.cw, "filter_log_events", fake_filter)

    page = await history.search_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s",
        query="x", is_regex=False, start_ms=None, end_ms=None, token=None,
    )
    # 攒够 3 行即停 (翻了 3 页)
    assert [l.log for l in page.lines] == ["L1", "L2", "L3"]
    assert calls["n"] == 3
    assert page.next_token == "tok3"


@pytest.mark.asyncio
async def test_search_page_respects_max_pages(monkeypatch) -> None:
    # 稀疏命中 (每页空但有 token): 最多翻 _FILTER_MAX_PAGES 页就返回, 不死翻。
    monkeypatch.setattr(history, "_FILTER_TARGET_LINES", 100)
    monkeypatch.setattr(history, "_FILTER_MAX_PAGES", 4)
    calls = {"n": 0}

    async def fake_filter(*, log_group, stream, filter_pattern, start_ms,
                          end_ms, next_token, limit):
        calls["n"] += 1
        return {"events": [], "next_token": f"tok{calls['n']}"}  # 恒非空 token

    monkeypatch.setattr(history.cw, "filter_log_events", fake_filter)

    page = await history.search_page(
        cluster_tag="ct", cluster_arn="arn:.../cid", stream="s",
        query="rare", is_regex=False, start_ms=None, end_ms=None, token=None,
    )
    assert calls["n"] == 4  # 撞上限停
    assert page.lines == []
    assert page.next_token == "tok4"  # 带 token, 前端可继续


@pytest.mark.asyncio
async def test_list_devinstance_streams_dual_container_numbered_independently(monkeypatch) -> None:
    # 同一 pod: 2 条 workspace (重启产两条) + 1 条 direct-ssh-init + 1 条 sidecar (过滤)。
    # workspace 按 first_ts 升序编号 (#1/#2); direct-ssh-init 独立编号 (#1)。
    ws = "alice-dev01-m7cpglvzre"
    pod = f"workspace-{ws}-698c5f86b5-c682s"
    p = "FluentBit/kube.var.log.containers."
    workspace_stream = f"{p}{pod}_ns_workspace-c1.log"
    workspace_stream2 = f"{p}{pod}_ns_workspace-c4.log"   # same pod, 2nd workspace stream (重启)
    ssh_stream = f"{p}{pod}_ns_direct-ssh-init-c2.log"
    sidecar = f"{p}{pod}_ns_ssm-agent-sidecar-c3.log"

    async def fake_describe(*, log_group, prefix):
        return [
            {"logStreamName": ssh_stream, "firstEventTimestamp": 100,
             "lastEventTimestamp": 150},
            {"logStreamName": workspace_stream, "firstEventTimestamp": 200,
             "lastEventTimestamp": 300},
            {"logStreamName": sidecar, "firstEventTimestamp": 50,
             "lastEventTimestamp": 60},
            {"logStreamName": workspace_stream2, "firstEventTimestamp": 400,
             "lastEventTimestamp": 500},
        ]

    monkeypatch.setattr(history.cw, "describe_log_streams_by_prefix", fake_describe)

    streams = await history.list_devinstance_streams(
        k8s_workspace_name=ws, cluster_tag="ct", cluster_arn="arn:.../cid"
    )
    names = {s.stream_name for s in streams}
    # sidecar 被过滤, 只剩 3 条
    assert names == {workspace_stream, workspace_stream2, ssh_stream}
    seq = {s.stream_name: s.seq for s in streams}
    # workspace 按 first_ts 升序独立编号: 早 (#1) → 晚 (#2)
    assert seq[workspace_stream] == 1
    assert seq[workspace_stream2] == 2
    assert seq[ssh_stream] == 1   # direct-ssh-init independent, still #1
    # 最终按 last_ts 倒序: workspace_stream2 (last_ts=500) 排首位
    assert streams[0].stream_name == workspace_stream2
