"""TrainingInformer 子类特有逻辑测试。

通用 watch/毒丸隔离/401/410 逻辑已在 test_base_informer.py 覆盖 (基类 CRInformer);
此文件只测训练子类特有: derive_status_md (用 worker/phase.py) + resolve_ids
(训练 label / namespace 反推) + 毒丸隔离在子类实例上仍生效。
"""
import pytest

from worker.informers.training import TrainingInformer


def _inf():
    return TrainingInformer(context=None)


def test_coordinates():
    inf = _inf()
    assert inf.group == "sagemaker.amazonaws.com"
    assert inf.plural == "hyperpodpytorchjobs"
    assert inf.resource_kind == "HyperPodPyTorchJob"
    assert inf.resource_type == "train"


@pytest.mark.asyncio
async def test_derive_status_md_phase():
    """derive_status_md 复用 worker/phase.py: conditions → phase + 时间字段."""
    inf = _inf()
    cr = {
        "status": {
            "conditions": [
                {"type": "Running", "status": "True",
                 "lastTransitionTime": "2026-06-09T10:00:00Z"},
            ]
        }
    }
    md = await inf.derive_status_md(cr)
    assert md["phase"] == "Running"
    assert md["started_at"] == "2026-06-09T10:00:00Z"
    assert "ended_at" in md
    assert "last_condition_message" in md


@pytest.mark.asyncio
async def test_resolve_ids_from_labels():
    """有 platform label → 直接返 (job_id, ws_id)."""
    inf = _inf()
    cr = {"metadata": {"labels": {
        "platform.hyperpod.io/training-job-id": "job-1",
        "platform.hyperpod.io/workspace-id": "ws-1",
    }}}
    assert await inf.resolve_ids(cr) == ("job-1", "ws-1")


@pytest.mark.asyncio
async def test_resolve_ids_bypass_ui_namespace_fallback(monkeypatch):
    """绕过 UI 提交 (无 label) → namespace 反推 ws, job_id 退化用 name."""
    inf = _inf()

    async def fake_get_ws_by_ns(db, _x, ns):
        return {"workspace_id": "ws-from-ns"} if ns == "hyperpod-ns-x" else None

    monkeypatch.setattr(
        "worker.informers.training.ws_crud.get_workspace_by_namespace",
        fake_get_ws_by_ns,
    )
    cr = {"metadata": {"namespace": "hyperpod-ns-x", "name": "raw-job", "uid": "u1"}}
    assert await inf.resolve_ids(cr) == ("u1", "ws-from-ns")  # uid 优先于 name


@pytest.mark.asyncio
async def test_resolve_ids_unknown_namespace_returns_none(monkeypatch):
    """namespace 反推不到 ws (非平台管理的 ns) → None → 跳过."""
    inf = _inf()

    async def fake_get_ws_by_ns(db, _x, ns):
        return None

    monkeypatch.setattr(
        "worker.informers.training.ws_crud.get_workspace_by_namespace",
        fake_get_ws_by_ns,
    )
    cr = {"metadata": {"namespace": "kube-system", "name": "foreign"}}
    assert await inf.resolve_ids(cr) is None


@pytest.mark.asyncio
async def test_poison_isolation_on_instance(monkeypatch):
    """毒丸隔离 (基类能力) 在训练子类实例上仍生效."""
    inf = _inf()

    async def boom(cr):
        raise ValueError("poison")

    monkeypatch.setattr(inf, "_reconcile", boom)
    await inf._safe_reconcile({"metadata": {"name": "bad"}})  # 不抛
    assert inf.get_error_count() == 1


@pytest.mark.asyncio
async def test_derive_status_md_includes_priority_class():
    """derive_status_md 读 kueue priority-class label 写进 md."""
    inf = _inf()
    cr = {
        "metadata": {"labels": {
            "kueue.x-k8s.io/priority-class": "training-default",
        }},
        "status": {"conditions": []},
    }
    md = await inf.derive_status_md(cr)
    assert md["priority_class"] == "training-default"


@pytest.mark.asyncio
async def test_derive_status_md_priority_class_missing_is_none():
    """无 priority-class label → priority_class=None, 不报错."""
    inf = _inf()
    cr = {"metadata": {"labels": {}}, "status": {"conditions": []}}
    md = await inf.derive_status_md(cr)
    assert md["priority_class"] is None
