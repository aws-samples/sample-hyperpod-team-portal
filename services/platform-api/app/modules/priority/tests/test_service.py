"""优先级管理 service 测试 (mock K8s client + ws_crud, 不碰真集群)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.adapters.aws import scheduler_config as sc_mod
from app.modules.priority.orchestration import service


class _FakeK8s:
    def __init__(self):
        self.workloads = [
            {
                "metadata": {
                    "name": "hyperpodpytorchjob-ddp-x-abc-123",
                    "ownerReferences": [{"kind": "HyperPodPyTorchJob", "name": "ddp-x-abc"}],
                },
                "spec": {"priority": 80, "priorityClassName": "common-priority", "queueName": "q"},
                "status": {"conditions": [{"type": "Admitted", "status": "True"}]},
            },
            {
                "metadata": {
                    "name": "rayjob-bob-ray-08-34gf9pgfrh-abc",
                    "ownerReferences": [{"kind": "RayJob", "name": "bob-ray-08-34gf9pgfrh"}],
                },
                "spec": {"priority": 80, "priorityClassName": "common-priority", "queueName": "q"},
                "status": {"conditions": [{"type": "Admitted", "status": "True"}]},
            },
        ]
        self.cq = {"spec": {"preemption": {"withinClusterQueue": "Never"}}}
        self.patched = {}

    async def list_workloads(self, namespace):
        return self.workloads

    async def find_workload_by_owner(self, namespace, cr_name):
        for wl in self.workloads:
            owners = wl["metadata"].get("ownerReferences", [])
            if any(o["name"] == cr_name for o in owners):
                return wl
        return None

    async def find_workload_for_task(self, namespace, task_type, cr_name):
        # fake: 真实现按 type 走 uid-based; 此处只验 service 编排。
        # 训练沿用 owner.name 匹配; 开发机/推理 (owner=Pod) 返回一个通用 Workload。
        if task_type in ("train", "rayjob"):
            return await self.find_workload_by_owner(namespace, cr_name)
        return {
            "metadata": {"name": f"pod-{cr_name}-xxx"},
            "spec": {"priority": 80, "priorityClassName": "common-priority"},
            "status": {"conditions": [{"type": "QuotaReserved", "status": "False"}]},
        }

    async def patch_task_priority_label(self, task_type, namespace, cr_name, pcn):
        self.patched = {"type": task_type, "cr": cr_name, "pcn": pcn}

    async def delete_workload(self, namespace, wl_name):
        self.deleted_workload = wl_name

    async def delete_deployment(self, namespace, name):
        self.deleted_deployment = name

    async def get_clusterqueue(self, name):
        return self.cq

    async def patch_clusterqueue_preemption(self, name, within):
        self.cq["spec"]["preemption"]["withinClusterQueue"] = within
        return self.cq


@pytest.fixture
def k8s():
    return _FakeK8s()


@pytest.fixture(autouse=True)
def mock_ws(monkeypatch):
    async def fake_ws(db, ws_id):
        return {"namespace": "hyperpod-ns-demo"}
    monkeypatch.setattr(service.ws_crud, "get_workspace", fake_ws)


@pytest.mark.asyncio
async def test_list_priority_classes_from_scheduler_config():
    fake_list = AsyncMock(return_value=[
        {"name": "inference-priority", "value": 100, "description": None},
        {"name": "training-priority", "value": 80, "description": None},
    ])
    with patch.object(sc_mod, "list_priority_classes", fake_list):
        rows = await service.list_priority_classes(_FakeK8s())
    assert [r["name"] for r in rows] == ["inference-priority", "training-priority"]
    fake_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_priority_class_calls_upsert_with_bare_name():
    fake_upsert = AsyncMock()
    with patch.object(sc_mod, "upsert_priority_class", fake_upsert):
        result = await service.create_priority_class(
            _FakeK8s(), name="newone", value=55, description="ignored"
        )
    call_kwargs = fake_upsert.await_args.kwargs
    assert call_kwargs["bare_name"] == "newone"
    assert call_kwargs["weight"] == 55
    assert result["name"] == "newone-priority"


@pytest.mark.asyncio
async def test_delete_priority_class_strips_suffix_from_input():
    fake_delete = AsyncMock()
    with patch.object(sc_mod, "delete_priority_class", fake_delete):
        await service.delete_priority_class(_FakeK8s(), name="training-priority")
    assert fake_delete.await_args.kwargs["bare_name"] == "training"


@pytest.fixture
def mock_sc_list(monkeypatch):
    """patch_task_priority 内部调 list_priority_classes → sc_mod.list_priority_classes.
    提供与 _FakeK8s.wpcs 对应的档位数据 (common 80, high 95)."""
    async def _fake_list(_cluster_name):
        return [
            {"name": "high-priority", "value": 95, "description": None},
            {"name": "common-priority", "value": 80, "description": None},
        ]
    monkeypatch.setattr(sc_mod, "list_priority_classes", _fake_list)


@pytest.mark.asyncio
class TestWorkloadPriority:
    @pytest.fixture(autouse=True)
    def _sc_list(self, mock_sc_list):
        """所有 patch_task_priority 测试都需要档位列表走 SageMaker fake."""

    async def test_list_workloads(self, k8s):
        rows = await service.list_workloads(k8s, "ws1")
        assert rows[0]["owner_name"] == "ddp-x-abc"
        assert rows[0]["admitted"] is True
        assert rows[0]["priority"] == 80

    async def test_patch_task_priority(self, k8s):
        # task_type 由前端 (TaskRow.kind) 传, 不再从 owner kind 反推
        r = await service.patch_task_priority(
            k8s, "ws1", "train", "ddp-x-abc", "high-priority"
        )
        assert r["priority"] == 95  # high 的 value
        assert k8s.patched["type"] == "train"
        assert k8s.patched["pcn"] == "high-priority"
        # 训练: 删 Workload (Kueue 按 CR 新 label 重建)
        assert k8s.deleted_workload == "hyperpodpytorchjob-ddp-x-abc-123"

    async def test_patch_rayjob_deletes_workload(self, k8s):
        # rayjob: Workload owned by RayJob CR (同训练) → 删 Workload 而非删 Deployment。
        # (回归守护: rayjob 曾误落 else 分支去删不存在的 Deployment → 404。)
        r = await service.patch_task_priority(
            k8s, "ws1", "rayjob", "bob-ray-08-34gf9pgfrh", "high-priority"
        )
        assert r["priority"] == 95
        assert k8s.patched["type"] == "rayjob"
        assert k8s.deleted_workload == "rayjob-bob-ray-08-34gf9pgfrh-abc"
        assert getattr(k8s, "deleted_deployment", None) is None  # rayjob 不删 Deployment

    async def test_patch_dev_deletes_deployment(self, k8s):
        # 开发机: 改 CR label + 删 Deployment workspace-{cr_name} (operator 重建)
        await service.patch_task_priority(
            k8s, "ws1", "dev", "bob-dev-05-aba939", "high-priority"
        )
        assert k8s.patched["type"] == "dev"
        assert k8s.deleted_deployment == "workspace-bob-dev-05-aba939"
        assert getattr(k8s, "deleted_workload", None) is None  # dev 不删 Workload

    async def test_patch_inference_deletes_deployment(self, k8s):
        # 推理: Deployment 名 = cr_name (无 workspace- 前缀)
        await service.patch_task_priority(
            k8s, "ws1", "inference", "ccc-619ade", "high-priority"
        )
        assert k8s.patched["type"] == "inference"
        assert k8s.deleted_deployment == "ccc-619ade"

    async def test_patch_task_not_found(self, k8s):
        with pytest.raises(Exception) as exc:
            await service.patch_task_priority(
                k8s, "ws1", "train", "no-such-task", "high-priority"
            )
        assert "404" in str(exc.value) or "未找到" in str(exc.value)

    async def test_patch_unknown_class(self, k8s):
        with pytest.raises(Exception) as exc:
            await service.patch_task_priority(
                k8s, "ws1", "train", "ddp-x-abc", "no-such-class"
            )
        assert "404" in str(exc.value) or "不存在" in str(exc.value)

    async def test_patch_dynamo_rejected(self, k8s):
        # 多机推理暂不支持改优先级 → 友好 400 (而非 _job_uid_for_task 抛的 500)。
        with pytest.raises(Exception) as exc:
            await service.patch_task_priority(
                k8s, "ws1", "dynamo", "bob-multi-abc", "high-priority"
            )
        assert "400" in str(exc.value) or "暂不支持" in str(exc.value)


@pytest.mark.asyncio
async def test_create_priority_class_conflict_maps_409():
    from fastapi import HTTPException
    fake = AsyncMock(side_effect=sc_mod.SchedulerConfigError(
        "update-cluster-scheduler-config failed: WorkloadPriorityClass x already exists and is not managed by SageMaker"
    ))
    with patch.object(sc_mod, "upsert_priority_class", fake):
        with pytest.raises(HTTPException) as ei:
            await service.create_priority_class(_FakeK8s(), name="x", value=80, description=None)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_list_priority_classes_not_configured_maps_400():
    from fastapi import HTTPException
    fake = AsyncMock(side_effect=sc_mod.SchedulerConfigError(
        "hyperpod_cluster_name is empty; scheduler config API unavailable"
    ))
    with patch.object(sc_mod, "list_priority_classes", fake):
        with pytest.raises(HTTPException) as ei:
            await service.list_priority_classes(_FakeK8s())
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_priority_class_api_failure_maps_502():
    from fastapi import HTTPException
    fake = AsyncMock(side_effect=sc_mod.SchedulerConfigError(
        "describe-cluster-scheduler-config failed: throttled"
    ))
    with patch.object(sc_mod, "delete_priority_class", fake):
        with pytest.raises(HTTPException) as ei:
            await service.delete_priority_class(_FakeK8s(), name="x-priority")
    assert ei.value.status_code == 502


@pytest.mark.asyncio
async def test_update_priority_class_value_none_returns_current():
    from app.adapters.aws import scheduler_config as sc_mod
    fake_list = AsyncMock(return_value=[
        {"name": "training-priority", "value": 80, "description": None},
    ])
    with patch.object(sc_mod, "list_priority_classes", fake_list):
        row = await service.update_priority_class(_FakeK8s(), name="training-priority", value=None, description=None)
    assert row["name"] == "training-priority"
    assert row["value"] == 80


@pytest.mark.asyncio
async def test_update_priority_class_value_none_not_found_404():
    from fastapi import HTTPException
    from app.adapters.aws import scheduler_config as sc_mod
    fake_list = AsyncMock(return_value=[])
    with patch.object(sc_mod, "list_priority_classes", fake_list):
        with pytest.raises(HTTPException) as ei:
            await service.update_priority_class(_FakeK8s(), name="ghost-priority", value=None, description=None)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_create_priority_class_strips_suffix_from_full_name_input():
    from app.adapters.aws import scheduler_config as sc_mod
    fake_upsert = AsyncMock()
    with patch.object(sc_mod, "upsert_priority_class", fake_upsert):
        result = await service.create_priority_class(_FakeK8s(), name="newone-priority", value=55, description=None)
    assert fake_upsert.await_args.kwargs["bare_name"] == "newone"
    assert result["name"] == "newone-priority"


@pytest.mark.asyncio
class TestPreemption:
    async def test_get(self, k8s):
        r = await service.get_preemption(k8s, "ws1")
        assert r["within_cluster_queue"] == "Never"
        assert r["cluster_queue"] == "hyperpod-ns-demo-clusterqueue"

    async def test_set(self, k8s):
        r = await service.set_preemption(k8s, "ws1", "LowerPriority")
        assert r["within_cluster_queue"] == "LowerPriority"
        assert k8s.cq["spec"]["preemption"]["withinClusterQueue"] == "LowerPriority"
