from worker.heartbeat import Heartbeat
from worker.health import health_status


def test_healthy_when_fresh():
    hb = Heartbeat()
    hb.mark_progress()
    code, body = health_status(hb, threshold=900)
    assert code == 200
    assert body["status"] == "ok"


def test_unhealthy_when_stalled(monkeypatch):
    hb = Heartbeat()
    fake = [1000.0]
    monkeypatch.setattr("worker.heartbeat.time.monotonic", lambda: fake[0])
    hb.mark_progress()
    fake[0] = 1000.0 + 901.0
    code, body = health_status(hb, threshold=900)
    assert code == 503
    assert body["status"] == "stalled"


from worker.health import health_status_multi


def test_health_multi_ok_if_any_fresh():
    hb1, hb2 = Heartbeat(), Heartbeat()
    hb1.mark_progress()
    code, body = health_status_multi([hb1, hb2], threshold=900)
    assert code == 200
    assert body["status"] == "ok"


def test_health_multi_503_if_all_stale(monkeypatch):
    fake = [1000.0]
    monkeypatch.setattr("worker.heartbeat.time.monotonic", lambda: fake[0])
    hb1, hb2 = Heartbeat(), Heartbeat()
    hb1.mark_progress()
    hb2.mark_progress()
    fake[0] = 1000.0 + 901.0
    code, body = health_status_multi([hb1, hb2], threshold=900)
    assert code == 503
    assert body["status"] == "stalled"
