"""InferenceInformer 子类特有逻辑测试。"""
import pytest

from worker.informers import inference as inference_mod
from worker.informers.inference import InferenceInformer


def _inf():
    return InferenceInformer(context=None)


def _mock_2hop(monkeypatch, pods, wl_conds):
    """mock 推理 2 跳: list_pods_by_label_selector → list_workloads_by_job_uid。"""
    async def fake_pods(self, ns, selector):
        return pods

    async def fake_wls(self, ns, uid):
        return [{"metadata": {"creationTimestamp": "2026-06-02T10:00:00Z"},
                 "status": {"conditions": wl_conds}}]

    monkeypatch.setattr(inference_mod.K8sClient, "list_pods_by_label_selector", fake_pods)
    monkeypatch.setattr(inference_mod.K8sClient, "list_workloads_by_job_uid", fake_wls)


def test_coordinates():
    inf = _inf()
    assert inf.group == "inference.sagemaker.aws.amazon.com"
    assert inf.version == "v1"
    assert inf.plural == "inferenceendpointconfigs"
    assert inf.resource_type == "inference"
    assert inf.resource_kind == "InferenceEndpointConfig"


@pytest.mark.asyncio
async def test_derive_status_md_overall_state():
    inf = _inf()
    status = {
        "state": "InProgress",
        "conditions": [{"type": "Available", "status": "True",
                        "message": "ready"}],
        "deploymentStatus": {
            "deploymentObjectOverallState": "DeploymentComplete",
            "status": {"conditions": []},
        },
        "endpointUrl": "http://alb/x",
    }
    cr = {
        "metadata": {"labels": {
            "kueue.x-k8s.io/priority-class": "inference-default"}},
        "status": status,
    }
    md = await inf.derive_status_md(cr)
    # phase = deploymentObjectOverallState 原值
    assert md["phase"] == "DeploymentComplete"
    assert md["endpoint_url"] == "http://alb/x"
    assert md["last_condition_message"] == "ready"
    assert md["priority_class"] == "inference-default"
    # status_detail = {state, conditions, deploymentStatus}
    assert md["status_detail"] == {
        "state": "InProgress",
        "conditions": [{"type": "Available", "status": "True",
                        "message": "ready"}],
        "deploymentStatus": {
            "deploymentObjectOverallState": "DeploymentComplete",
            "status": {"conditions": []},
        },
    }


@pytest.mark.asyncio
async def test_derive_status_md_overall_state_missing_falls_back_to_state():
    inf = _inf()
    cr = {"metadata": {"labels": {}}, "status": {"state": "Creating"}}
    md = await inf.derive_status_md(cr)
    # deploymentObjectOverallState 缺失 → 回退 status.state
    assert md["phase"] == "Creating"
    assert md["priority_class"] is None
    assert md["status_detail"] == {
        "state": "Creating", "conditions": [], "deploymentStatus": {},
    }


@pytest.mark.asyncio
async def test_kueue_status_mirrors_workload_running(monkeypatch):
    # 2 跳取最新 Pod (2个不同 creationTimestamp) → 最新的 uid 反查 Workload → PodsReady
    pods = [
        {"metadata": {"uid": "old", "creationTimestamp": "2026-06-01T00:00:00Z"}},
        {"metadata": {"uid": "new", "creationTimestamp": "2026-06-02T00:00:00Z"}},
    ]
    captured = {}

    async def fake_pods(self, ns, selector):
        return pods

    async def fake_wls(self, ns, uid):
        captured["uid"] = uid
        return [{"metadata": {"creationTimestamp": "2026-06-02T10:00:00Z"},
                 "status": {"conditions": [
                     {"type": "QuotaReserved", "status": "True"},
                     {"type": "Admitted", "status": "True"},
                     {"type": "PodsReady", "status": "True"}]}}]

    monkeypatch.setattr(inference_mod.K8sClient, "list_pods_by_label_selector", fake_pods)
    monkeypatch.setattr(inference_mod.K8sClient, "list_workloads_by_job_uid", fake_wls)

    inf = _inf()
    cr = {"metadata": {"name": "ep", "namespace": "ns1", "labels": {}}, "status": {
        "deploymentStatus": {"deploymentObjectOverallState": "DeploymentComplete"}}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "PodsReady"
    # 用最新创建的 Pod uid 反查
    assert captured["uid"] == "new"


@pytest.mark.asyncio
async def test_kueue_status_queued_mirrors_workload(monkeypatch):
    _mock_2hop(monkeypatch, [{"metadata": {"uid": "p1"}}],
               [{"type": "QuotaReserved", "status": "False", "reason": "Pending"}])
    inf = _inf()
    cr = {"metadata": {"name": "ep", "namespace": "ns1", "labels": {}},
          "status": {"state": "DeploymentInProgress"}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "Queued"


@pytest.mark.asyncio
async def test_kueue_status_finished_when_no_pod_and_terminal(monkeypatch):
    # 查不到 Pod + CR 终态 (Stopped ∈ _INF_FINISHED) → Finished
    async def fake_no_pods(self, ns, selector):
        return []
    monkeypatch.setattr(inference_mod.K8sClient, "list_pods_by_label_selector", fake_no_pods)
    inf = _inf()
    cr = {"metadata": {"name": "ep", "namespace": "ns1", "labels": {}},
          "status": {"state": "Stopped"}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "Finished"


@pytest.mark.asyncio
async def test_kueue_status_none_when_no_pod_and_running(monkeypatch):
    # 查不到 Pod + CR 运行态 (DeploymentComplete 不在 _INF_FINISHED) → None (保持旧值)
    async def fake_no_pods(self, ns, selector):
        return []
    monkeypatch.setattr(inference_mod.K8sClient, "list_pods_by_label_selector", fake_no_pods)
    inf = _inf()
    cr = {"metadata": {"name": "ep", "namespace": "ns1", "labels": {}}, "status": {
        "deploymentStatus": {"deploymentObjectOverallState": "DeploymentComplete"}}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] is None


@pytest.mark.asyncio
async def test_resolve_ids_from_labels():
    inf = _inf()
    cr = {"metadata": {"labels": {
        "platform.hyperpod.io/inference-id": "inf-1",
        "platform.hyperpod.io/workspace-id": "ws-1",
    }}}
    assert await inf.resolve_ids(cr) == ("inf-1", "ws-1")


@pytest.mark.asyncio
async def test_resolve_ids_namespace_fallback(monkeypatch):
    inf = _inf()

    async def fake_get_ws_by_ns(db, _x, ns):
        return {"workspace_id": "ws-ns"} if ns == "hyperpod-ns-x" else None

    monkeypatch.setattr(
        "worker.informers.inference.ws_crud.get_workspace_by_namespace",
        fake_get_ws_by_ns,
    )
    cr = {"metadata": {"namespace": "hyperpod-ns-x", "name": "raw", "uid": "u1"}}
    assert await inf.resolve_ids(cr) == ("u1", "ws-ns")
