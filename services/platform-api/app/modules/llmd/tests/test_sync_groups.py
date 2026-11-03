"""llmd pod 分组 + workload 关联: 从 pod 名解析 group, 按 Workload ownerRef 关联 workload 名。"""
from app.modules.llmd.response.builders import _pod_group, _associate_workloads


def test_pod_group_leader():
    assert _pod_group("bob-2-replica-hiwlxln6va-multi-0", "leader",
                      "bob-2-replica-hiwlxln6va") == "0"


def test_pod_group_worker():
    assert _pod_group("bob-2-replica-hiwlxln6va-multi-0-1", "worker",
                      "bob-2-replica-hiwlxln6va") == "0"


def test_pod_group_group1():
    assert _pod_group("bob-2-replica-hiwlxln6va-multi-1-1", "worker",
                      "bob-2-replica-hiwlxln6va") == "1"


def test_pod_group_gateway():
    assert _pod_group("bob-2-replica-hiwlxln6va-gateway-58b-98k", "gateway",
                      "bob-2-replica-hiwlxln6va") is None


def test_pod_group_non_matching_prefix():
    # pod 名不以 <base>-multi- 开头 (异常/其他任务) → None
    assert _pod_group("some-other-pod-xyz", "leader",
                      "bob-2-replica-hiwlxln6va") is None


def test_associate_workloads_maps_pod_to_workload_name():
    workloads = [
        {"metadata": {"name": "leaderworkerset-t-multi-0-abc12",
                      "ownerReferences": [
                          {"kind": "LeaderWorkerSet", "name": "t-multi"},
                          {"kind": "Pod", "name": "t-multi-0"},
                          {"kind": "Pod", "name": "t-multi-0-1"}]}},
        {"metadata": {"name": "pod-t-gateway-xx-yy-def34",
                      "ownerReferences": [{"kind": "Pod", "name": "t-gateway-xx-yy"}]}},
    ]
    out = _associate_workloads(workloads)
    assert out["t-multi-0"] == "leaderworkerset-t-multi-0-abc12"
    assert out["t-multi-0-1"] == "leaderworkerset-t-multi-0-abc12"
    assert out["t-gateway-xx-yy"] == "pod-t-gateway-xx-yy-def34"
