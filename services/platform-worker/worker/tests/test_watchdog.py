from worker.heartbeat import Heartbeat
from worker.watchdog import is_stalled


def test_not_stalled_when_fresh(monkeypatch):
    hb = Heartbeat()
    hb.mark_progress()
    assert is_stalled(hb, threshold=900) is False


def test_stalled_when_over_threshold(monkeypatch):
    hb = Heartbeat()
    fake = [1000.0]
    monkeypatch.setattr("worker.heartbeat.time.monotonic", lambda: fake[0])
    hb.mark_progress()              # last = 1000
    fake[0] = 1000.0 + 901.0        # 901s 后, 超 900 阈值
    assert is_stalled(hb, threshold=900) is True


def test_not_stalled_just_under_threshold(monkeypatch):
    hb = Heartbeat()
    fake = [1000.0]
    monkeypatch.setattr("worker.heartbeat.time.monotonic", lambda: fake[0])
    hb.mark_progress()
    fake[0] = 1000.0 + 899.0        # 899s, 未到阈值
    assert is_stalled(hb, threshold=900) is False


from worker.watchdog import all_stalled


def test_all_stalled_false_if_any_fresh():
    hb1, hb2 = Heartbeat(), Heartbeat()
    hb1.mark_progress()  # hb1 新鲜, hb2 从未 → 不算全 stale
    assert all_stalled([hb1, hb2], threshold=900) is False


def test_all_stalled_true_when_all_stale(monkeypatch):
    fake = [1000.0]
    monkeypatch.setattr("worker.heartbeat.time.monotonic", lambda: fake[0])
    hb1, hb2 = Heartbeat(), Heartbeat()
    hb1.mark_progress()
    hb2.mark_progress()
    fake[0] = 1000.0 + 901.0
    assert all_stalled([hb1, hb2], threshold=900) is True
