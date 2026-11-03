"""代理 gate 负向判定: 含 Stopped/Terminating 才挡, 其余 (含 Available/空串) 放行。"""
from app.modules.devinstance.api.router import _proxy_blocked_phase


def test_available_not_blocked():
    assert _proxy_blocked_phase("Available") is False


def test_joined_available_not_blocked():
    assert _proxy_blocked_phase("Initialized/Available") is False


def test_empty_phase_not_blocked():
    # 还没起来 (空串): gate 放行, 由下游 pod-IP 检查返 503
    assert _proxy_blocked_phase("") is False


def test_stopped_blocked():
    assert _proxy_blocked_phase("Stopped") is True


def test_terminating_blocked():
    assert _proxy_blocked_phase("Terminating") is True


def test_none_not_blocked():
    assert _proxy_blocked_phase(None) is False
