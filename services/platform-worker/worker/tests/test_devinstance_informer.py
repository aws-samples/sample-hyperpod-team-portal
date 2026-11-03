"""DevInstanceInformer 子类特有逻辑测试。"""
import pytest

from worker.informers import devinstance as devinstance_mod
from worker.informers.devinstance import DevInstanceInformer


def _inf():
    return DevInstanceInformer(context=None)


def _mock_2hop(monkeypatch, pods, wl_conds):
    async def fake_pods(self, ns, name):
        return pods

    async def fake_wls(self, ns, uid):
        return [{"metadata": {"creationTimestamp": "2026-06-02T10:00:00Z"},
                 "status": {"conditions": wl_conds}}]

    monkeypatch.setattr(devinstance_mod.K8sClient, "list_pods_by_workspace", fake_pods)
    monkeypatch.setattr(devinstance_mod.K8sClient, "list_workloads_by_job_uid", fake_wls)


def _mock_no_pods(monkeypatch):
    async def fake_no(self, ns, name):
        return []
    monkeypatch.setattr(devinstance_mod.K8sClient, "list_pods_by_workspace", fake_no)


def test_coordinates():
    inf = _inf()
    assert inf.group == "workspace.jupyter.org"
    assert inf.version == "v1alpha1"
    assert inf.plural == "workspaces"
    assert inf.resource_type == "dev"
    assert inf.resource_kind == "Workspace"


@pytest.mark.asyncio
async def test_derive_status_md_running():
    inf = _inf()
    cr = {
        "metadata": {"labels": {
            "kueue.x-k8s.io/priority-class": "devinstance-default"}},
        "status": {"conditions": [
            {"type": "Available", "status": "True",
             "lastTransitionTime": "2026-06-09T12:08:14Z",
             "message": "Workspace is ready"},
        ]},
    }
    md = await inf.derive_status_md(cr)
    # 原始 phase: 所有 True type 拼接
    assert md["phase"] == "Available"
    assert md["started_at"] == "2026-06-09T12:08:14Z"
    assert md["priority_class"] == "devinstance-default"
    assert md["last_condition_message"] == "Workspace is ready"
    # status_detail = 所有 status==True 的 condition 数组
    assert md["status_detail"] == [
        {"type": "Available", "status": "True",
         "lastTransitionTime": "2026-06-09T12:08:14Z",
         "message": "Workspace is ready"},
    ]


@pytest.mark.asyncio
async def test_derive_status_md_multiple_true_single_phase(monkeypatch):
    _mock_no_pods(monkeypatch)
    inf = _inf()
    cr = {"metadata": {"labels": {}}, "status": {"conditions": [
        {"type": "Initialized", "status": "True"},
        {"type": "Available", "status": "True"},
        {"type": "Degraded", "status": "False"},
    ]}}
    md = await inf.derive_status_md(cr)
    # 单状态: 无时间戳 → 按优先级, Available 高于 Initialized → "Available"
    assert md["phase"] == "Available"
    # status_detail 仍是所有 True condition 数组
    assert [c["type"] for c in md["status_detail"]] == [
        "Initialized", "Available"]


@pytest.mark.asyncio
async def test_derive_status_md_empty_no_priority():
    inf = _inf()
    cr = {"metadata": {"labels": {}}, "status": {"conditions": []}}
    md = await inf.derive_status_md(cr)
    assert md["phase"] == ""
    assert md["started_at"] is None
    assert md["priority_class"] is None
    # 无 True condition → status_detail 空数组
    assert md["status_detail"] == []


@pytest.mark.asyncio
async def test_derive_status_md_ended_at_from_stopped():
    inf = _inf()
    cr = {"metadata": {"labels": {}}, "status": {"conditions": [
        {"type": "Stopped", "status": "True",
         "lastTransitionTime": "2026-06-10T01:00:00Z"},
    ]}}
    md = await inf.derive_status_md(cr)
    assert md["phase"] == "Stopped"
    assert md["ended_at"] == "2026-06-10T01:00:00Z"


@pytest.mark.asyncio
async def test_kueue_status_mirrors_workload_running(monkeypatch):
    # 2 跳取最新 Pod → Workload PodsReady
    _mock_2hop(monkeypatch, [{"metadata": {"uid": "p1"}}],
               [{"type": "QuotaReserved", "status": "True"},
                {"type": "Admitted", "status": "True"},
                {"type": "PodsReady", "status": "True"}])
    inf = _inf()
    cr = {"metadata": {"name": "dev-x", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Available", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "PodsReady"


@pytest.mark.asyncio
async def test_kueue_status_finished_when_no_pod_and_stopped(monkeypatch):
    # 查不到 Pod + CR 终态 (Stopped) → Finished
    _mock_no_pods(monkeypatch)
    inf = _inf()
    cr = {"metadata": {"name": "dev-x", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Stopped", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "Finished"


@pytest.mark.asyncio
async def test_kueue_status_none_when_no_pod_and_available(monkeypatch):
    # 查不到 Pod + CR 非终态 (Available) → None (保持旧值)
    _mock_no_pods(monkeypatch)
    inf = _inf()
    cr = {"metadata": {"name": "dev-x", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Available", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] is None


@pytest.mark.asyncio
async def test_kueue_status_stopped_short_circuits_finished_despite_stale_workload(monkeypatch):
    # 竞态: CR 已 Stopped, 但 Workload 还没被级联删 (仍返 Admitted)。
    # CR 终态优先于 Workload 残留 → 直接 Finished, 且不发起 Workload 查询 (短路)。
    queried = {"pods": False, "wls": False}

    async def fake_pods(self, ns, name):
        queried["pods"] = True
        return [{"metadata": {"uid": "p1"}}]

    async def fake_wls(self, ns, uid):
        queried["wls"] = True
        return [{"metadata": {"creationTimestamp": "2026-06-02T10:00:00Z"},
                 "status": {"conditions": [
                     {"type": "QuotaReserved", "status": "True"},
                     {"type": "Admitted", "status": "True"}]}}]

    monkeypatch.setattr(devinstance_mod.K8sClient, "list_pods_by_workspace", fake_pods)
    monkeypatch.setattr(devinstance_mod.K8sClient, "list_workloads_by_job_uid", fake_wls)

    inf = _inf()
    cr = {"metadata": {"name": "dev-x", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Stopped", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "Finished"
    # 短路: CR 终态时不应查 Workload (避免被残留 Workload 误导 + 省查询)
    assert queried["pods"] is False
    assert queried["wls"] is False


@pytest.mark.asyncio
async def test_resolve_ids_from_labels():
    inf = _inf()
    cr = {"metadata": {"labels": {
        "platform.hyperpod.io/dev-instance-id": "dev-1",
        "platform.hyperpod.io/workspace-id": "ws-1",
    }}}
    assert await inf.resolve_ids(cr) == ("dev-1", "ws-1")


@pytest.mark.asyncio
async def test_resolve_ids_namespace_fallback(monkeypatch):
    inf = _inf()

    async def fake_get_ws_by_ns(db, _x, ns):
        return {"workspace_id": "ws-ns"} if ns == "hyperpod-ns-x" else None

    monkeypatch.setattr(
        "worker.informers.devinstance.ws_crud.get_workspace_by_namespace",
        fake_get_ws_by_ns,
    )
    cr = {"metadata": {"namespace": "hyperpod-ns-x", "name": "raw", "uid": "u1"}}
    assert await inf.resolve_ids(cr) == ("u1", "ws-ns")


@pytest.mark.asyncio
async def test_resolve_ids_unknown_namespace_none(monkeypatch):
    inf = _inf()

    async def fake_get_ws_by_ns(db, _x, ns):
        return None

    monkeypatch.setattr(
        "worker.informers.devinstance.ws_crud.get_workspace_by_namespace",
        fake_get_ws_by_ns,
    )
    cr = {"metadata": {"namespace": "kube-system", "name": "foreign"}}
    assert await inf.resolve_ids(cr) is None
