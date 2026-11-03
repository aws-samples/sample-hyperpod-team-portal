"""derive_devinstance_phase 纯函数测试 (Workspace CR conditions → phase + started_at)。"""
from app.modules.devinstance.domain.phase import derive_devinstance_phase


def _cr(conds):
    return {"status": {"conditions": conds}}


def test_stopped():
    phase, started = derive_devinstance_phase(
        _cr([{"type": "Stopped", "status": "True", "lastTransitionTime": "t1"}])
    )
    assert phase == "Stopped"
    assert started is None


def test_running_by_available():
    phase, started = derive_devinstance_phase(
        _cr([{"type": "Available", "status": "True",
              "lastTransitionTime": "2026-06-09T12:08:14Z"}])
    )
    assert phase == "Running"
    assert started == "2026-06-09T12:08:14Z"  # started_at 从 Available.lastTransitionTime


def test_degraded():
    phase, started = derive_devinstance_phase(
        _cr([{"type": "Degraded", "status": "True", "lastTransitionTime": "t1"}])
    )
    assert phase == "Degraded"
    assert started is None


def test_creating_fallback():
    # 无 Available/Stopped/Degraded=True → Creating
    phase, started = derive_devinstance_phase(
        _cr([{"type": "Progressing", "status": "True", "lastTransitionTime": "t1"}])
    )
    assert phase == "Creating"
    assert started is None


def test_empty_conditions_is_creating():
    phase, started = derive_devinstance_phase(_cr([]))
    assert phase == "Creating"
    assert started is None


def test_stopped_takes_precedence_over_available():
    # 停止时 Available 可能残留 True, Stopped 优先
    phase, _ = derive_devinstance_phase(_cr([
        {"type": "Available", "status": "True", "lastTransitionTime": "t1"},
        {"type": "Stopped", "status": "True", "lastTransitionTime": "t2"},
    ]))
    assert phase == "Stopped"
