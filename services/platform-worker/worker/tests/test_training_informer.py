"""TrainingInformer 子类特有逻辑测试 (单状态 phase + status_detail + Workload镜像)。"""
from unittest.mock import AsyncMock

import pytest

from worker.informers import training as training_mod
from worker.informers.training import TrainingInformer


def _inf():
    return TrainingInformer(context=None)


def _mock_workload(monkeypatch, conds):
    """让 K8sClient.list_workloads_by_job_uid 返回带指定 conditions 的单个 Workload。"""
    async def fake_list(self, ns, uid):
        return [{"metadata": {"creationTimestamp": "2026-06-02T10:00:00Z"},
                 "status": {"conditions": conds}}]
    monkeypatch.setattr(training_mod.K8sClient, "list_workloads_by_job_uid", fake_list)


def _mock_pods(monkeypatch, phases):
    """让 K8sClient.list_pods_by_label_selector 返回指定 phase 的 Pod 列表。"""
    async def fake_pods(self, ns, selector):
        return [{"status": {"phase": p}} for p in phases]
    monkeypatch.setattr(
        training_mod.K8sClient, "list_pods_by_label_selector", fake_pods
    )


def test_coordinates():
    inf = _inf()
    assert inf.group == "sagemaker.amazonaws.com"
    assert inf.plural == "hyperpodpytorchjobs"
    assert inf.resource_type == "train"
    assert inf.resource_kind == "HyperPodPyTorchJob"


@pytest.mark.asyncio
async def test_derive_status_md_running_single_phase(monkeypatch):
    _mock_workload(monkeypatch, [{"type": "PodsReady", "status": "True"}])
    inf = _inf()
    status = {
        "conditions": [
            {"type": "Created", "status": "True",
             "lastTransitionTime": "2026-06-02T09:00:00Z"},
            {"type": "Running", "status": "True",
             "lastTransitionTime": "2026-06-02T10:00:00Z", "message": "ok"},
        ],
    }
    cr = {
        "metadata": {"uid": "u1", "namespace": "ns1", "labels": {
            "kueue.x-k8s.io/priority-class": "common-priority"}},
        "status": status,
    }
    md = await inf.derive_status_md(cr)
    # 单状态: 取 lastTransitionTime 最新 → Running (不再 Created/Running)
    assert md["phase"] == "Running"
    assert md["started_at"] == "2026-06-02T10:00:00Z"
    assert md["last_condition_message"] == "ok"
    assert md["priority_class"] == "common-priority"
    assert md["status_detail"] == status
    # kueue_status = Workload 镜像 → PodsReady
    assert md["kueue_status"] == "PodsReady"


@pytest.mark.asyncio
async def test_kueue_status_mirrors_workload_queued(monkeypatch):
    # 排队中 Workload (QR=False) → Queued
    _mock_workload(monkeypatch, [
        {"type": "QuotaReserved", "status": "False", "reason": "Pending"},
    ])
    inf = _inf()
    cr = {"metadata": {"uid": "u1", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Suspended", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "Queued"


@pytest.mark.asyncio
async def test_kueue_status_none_when_no_workload_and_cr_not_terminal(monkeypatch):
    # 查不到 Workload (返空) + CR 非终态 → None (保持DDB旧值不覆盖)
    async def fake_empty(self, ns, uid):
        return []
    monkeypatch.setattr(training_mod.K8sClient, "list_workloads_by_job_uid", fake_empty)
    inf = _inf()
    cr = {"metadata": {"uid": "u1", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Created", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] is None


@pytest.mark.asyncio
async def test_kueue_status_finished_when_no_workload_and_cr_terminal(monkeypatch):
    # 查不到 Workload + CR 终态 (Complete) → Finished
    async def fake_empty(self, ns, uid):
        return []
    monkeypatch.setattr(training_mod.K8sClient, "list_workloads_by_job_uid", fake_empty)
    inf = _inf()
    cr = {"metadata": {"uid": "u1", "namespace": "ns1", "labels": {}},
          "status": {"conditions": [{"type": "Complete", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "Finished"


def _failed_cr(clean_policy=None):
    """构造 Failed 训练 CR; clean_policy=None 表示 spec.runPolicy 缺 cleanPodPolicy。"""
    run_policy = {}
    if clean_policy is not None:
        run_policy["cleanPodPolicy"] = clean_policy
    return {
        "metadata": {"uid": "u1", "namespace": "ns1", "name": "job-x", "labels": {}},
        "spec": {"runPolicy": run_policy},
        "status": {"conditions": [{"type": "Failed", "status": "True"}]},
    }


@pytest.mark.asyncio
async def test_onlycomplete_pod_running_marks_occupying(monkeypatch):
    # cleanPodPolicy=OnlyComplete: 失败 Pod 留着 → 查 Pod, Running → 占卡 → occupying=True
    _mock_workload(monkeypatch, [
        {"type": "Admitted", "status": "True"},
        {"type": "PodsReady", "status": "True"},
        {"type": "Finished", "status": "True", "reason": "Failed"},
    ])
    _mock_pods(monkeypatch, ["Running"])
    inf = _inf()
    md = await inf.derive_status_md(_failed_cr("OnlyComplete"))
    assert md["kueue_status"] == "Finished"
    assert md["occupying_resources"] is True


@pytest.mark.asyncio
async def test_onlycomplete_pod_pending_marks_occupying(monkeypatch):
    # Pending 也占卡 (已调度绑节点, GPU 已分配)
    _mock_workload(monkeypatch, [
        {"type": "Finished", "status": "True", "reason": "Failed"},
    ])
    _mock_pods(monkeypatch, ["Pending"])
    inf = _inf()
    md = await inf.derive_status_md(_failed_cr("OnlyComplete"))
    assert md["occupying_resources"] is True


@pytest.mark.asyncio
async def test_onlycomplete_pod_gone_not_occupying(monkeypatch):
    # OnlyComplete 但 Pod 已没 (Succeeded) → 不占卡 → occupying=False
    _mock_workload(monkeypatch, [
        {"type": "Finished", "status": "True", "reason": "Failed"},
    ])
    _mock_pods(monkeypatch, ["Succeeded"])
    inf = _inf()
    md = await inf.derive_status_md(_failed_cr("OnlyComplete"))
    assert md["kueue_status"] == "Finished"
    assert md["occupying_resources"] is False


@pytest.mark.asyncio
async def test_cleanpod_all_failed_no_pod_query_not_occupying(monkeypatch):
    # cleanPodPolicy=All: 失败 Pod 注定被清 → 不查 Pod, 直接 occupying=False
    # (修死穴: informer 收不到 Pod 删除事件, 不能依赖事后翻 False; All 时 Failed 即判 False)
    queried = {"pods": False}

    async def fake_pods(self, ns, selector):
        queried["pods"] = True
        return [{"status": {"phase": "Running"}}]
    monkeypatch.setattr(
        training_mod.K8sClient, "list_pods_by_label_selector", fake_pods
    )
    _mock_workload(monkeypatch, [
        {"type": "Finished", "status": "True", "reason": "Failed"},
    ])
    inf = _inf()
    md = await inf.derive_status_md(_failed_cr("All"))
    assert md["kueue_status"] == "Finished"
    assert md["occupying_resources"] is False
    assert queried["pods"] is False  # All → 不查 Pod


@pytest.mark.asyncio
async def test_cleanpod_missing_treated_as_all(monkeypatch):
    # 缺 cleanPodPolicy (理论上 apiserver 会注入 default=All; 防御按 All 处理) → 不查 Pod
    queried = {"pods": False}

    async def fake_pods(self, ns, selector):
        queried["pods"] = True
        return [{"status": {"phase": "Running"}}]
    monkeypatch.setattr(
        training_mod.K8sClient, "list_pods_by_label_selector", fake_pods
    )
    _mock_workload(monkeypatch, [
        {"type": "Finished", "status": "True", "reason": "Failed"},
    ])
    inf = _inf()
    md = await inf.derive_status_md(_failed_cr(None))  # 无 cleanPodPolicy
    assert md["occupying_resources"] is False
    assert queried["pods"] is False


@pytest.mark.asyncio
async def test_running_not_finished_no_pod_query_no_occupying(monkeypatch):
    # 非 Finished (PodsReady) → 不查 Pod (只 Finished 才探占卡), occupying=False
    queried = {"pods": False}

    async def fake_pods(self, ns, selector):
        queried["pods"] = True
        return [{"status": {"phase": "Running"}}]
    monkeypatch.setattr(
        training_mod.K8sClient, "list_pods_by_label_selector", fake_pods
    )
    _mock_workload(monkeypatch, [
        {"type": "Admitted", "status": "True"},
        {"type": "PodsReady", "status": "True"},
    ])
    inf = _inf()
    cr = {"metadata": {"uid": "u1", "namespace": "ns1", "name": "job-x", "labels": {}},
          "spec": {"runPolicy": {"cleanPodPolicy": "OnlyComplete"}},
          "status": {"conditions": [{"type": "Running", "status": "True"}]}}
    md = await inf.derive_status_md(cr)
    assert md["kueue_status"] == "PodsReady"
    assert md["occupying_resources"] is False
    assert queried["pods"] is False  # 非 Finished 不查 Pod


@pytest.mark.asyncio
async def test_derive_status_md_empty_phase_and_empty_status_detail(monkeypatch):
    async def fake_empty(self, ns, uid):
        return []
    monkeypatch.setattr(training_mod.K8sClient, "list_workloads_by_job_uid", fake_empty)
    inf = _inf()
    cr = {"metadata": {"uid": "u1", "namespace": "ns1", "labels": {}}, "status": {}}
    md = await inf.derive_status_md(cr)
    assert md["phase"] == ""
    assert md["priority_class"] is None
    assert md["status_detail"] == {}
