"""endpoint_url 回填门槛: ALB 有地址【且】gateway 有 Ready 副本。

ALB 地址比 pod 就绪早得多 (75s vs 冷启动几分钟), 只看地址会给出调用即 503 的 URL。
"""
from app.modules.llmd.orchestration.sync import _gateway_has_ready_pod

_BASE = "llmd-x"


def _pod(name_label: str, ready: bool):
    return {
        "metadata": {"labels": {"app.kubernetes.io/name": name_label}},
        "status": {"conditions": [
            {"type": "Ready", "status": "True" if ready else "False"}
        ]},
    }


def test_ready_gateway_pod():
    assert _gateway_has_ready_pod([_pod(f"{_BASE}-gateway", True)], _BASE) is True


def test_gateway_pod_not_ready():
    assert _gateway_has_ready_pod([_pod(f"{_BASE}-gateway", False)], _BASE) is False


def test_worker_ready_does_not_count():
    # LWS worker Ready 不算 —— 请求打的是 gateway, 它没起来照样调不通
    assert _gateway_has_ready_pod([_pod(f"{_BASE}-multi", True)], _BASE) is False


def test_mixed_takes_gateway_only():
    pods = [_pod(f"{_BASE}-multi", True), _pod(f"{_BASE}-gateway", True)]
    assert _gateway_has_ready_pod(pods, _BASE) is True


def test_no_pods():
    assert _gateway_has_ready_pod([], _BASE) is False


def test_pod_without_labels():
    # informer 快照可能缺字段, 不能抛
    assert _gateway_has_ready_pod([{"metadata": {}, "status": {}}], _BASE) is False
