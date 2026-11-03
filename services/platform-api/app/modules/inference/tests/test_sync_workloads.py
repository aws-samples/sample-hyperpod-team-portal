"""推理 pod→workload 关联: 每 Pod 独立 pod 级 Workload (owner=Pod)。"""
from app.modules.inference.response.builders import _associate_workloads


def test_associate_workloads_maps_each_pod_to_own_workload():
    workloads = [
        {"metadata": {"name": "pod-ep-abc-p1-h1",
                      "ownerReferences": [{"kind": "Pod", "name": "ep-abc-p1"}]}},
        {"metadata": {"name": "pod-ep-abc-p2-h2",
                      "ownerReferences": [{"kind": "Pod", "name": "ep-abc-p2"}]}},
    ]
    out = _associate_workloads(workloads)
    assert out["ep-abc-p1"] == "pod-ep-abc-p1-h1"
    assert out["ep-abc-p2"] == "pod-ep-abc-p2-h2"


def test_associate_workloads_ignores_non_pod_owner_and_missing():
    workloads = [
        {"metadata": {"name": "wl-x", "ownerReferences": [{"kind": "ReplicaSet", "name": "rs"}]}},
        {"metadata": {"name": "wl-y"}},
    ]
    assert _associate_workloads(workloads) == {}
