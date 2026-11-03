import time

from worker.heartbeat import Heartbeat


def test_initial_age_is_large():
    """初始未 mark 时, 距上次进度应为很大值(视为从未进展)."""
    hb = Heartbeat()
    assert hb.seconds_since_progress() > 10_000


def test_mark_progress_resets_age():
    hb = Heartbeat()
    hb.mark_progress()
    assert hb.seconds_since_progress() < 1.0


def test_seconds_since_progress_grows(monkeypatch):
    """mark 之后时间推进, age 随之增长."""
    hb = Heartbeat()
    fake = [1000.0]
    monkeypatch.setattr("worker.heartbeat.time.monotonic", lambda: fake[0])
    hb.mark_progress()           # last = 1000
    fake[0] = 1000.0 + 42.0      # now = 1042
    assert abs(hb.seconds_since_progress() - 42.0) < 0.01
