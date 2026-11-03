"""sync_from_k8s 把 status_detail 写进 row (与 informer 字段集合一致)。"""
import pytest

from app.modules.inference.orchestration import sync as sync_mod


class _FakeK8s:
    def __init__(self, cr):
        self._cr = cr

    async def get_inference_endpoint(self, ns, name):
        return self._cr

    async def list_pods_by_label_selector(self, ns, selector):
        return []

    async def list_workloads(self, ns):
        return []


@pytest.mark.asyncio
async def test_sync_computes_status_detail_in_memory(monkeypatch):
    """sync 仍在 row 上算出 status_detail 供本次响应返回 (in-memory),
    但 后 status_detail 归 informer, 不进 dirty / 不落库
    所以这里 endpoint_url 不变时 crud.update 不应被调用。"""
    captured = {}

    async def fake_update(db, row):
        captured["row"] = dict(row)
        return row

    monkeypatch.setattr(sync_mod.crud, "update", fake_update)

    cr = {
        "status": {
            "state": "InProgress",
            "conditions": [{"type": "Available", "status": "True"}],
            "deploymentStatus": {
                "deploymentObjectOverallState": "DeploymentInProgress",
                "status": {"conditions": []},
            },
        }
    }
    row = {
        "id": "i1",
        "k8s_namespace": "ns",
        "k8s_endpoint_name": "ep",
        "phase": None,
        "endpoint_url": None,
        "last_condition_message": None,
        "status_detail": None,
    }
    out, conditions, pods, workloads = await sync_mod.sync_from_k8s(
        None, _FakeK8s(cr), row
    )
    # status_detail 仍被算进返回 row (in-memory 供响应)
    assert out["status_detail"] == {
        "state": "InProgress",
        "conditions": [{"type": "Available", "status": "True"}],
        "deploymentStatus": {
            "deploymentObjectOverallState": "DeploymentInProgress",
            "status": {"conditions": []},
        },
    }
    # 但 endpoint_url / alb_dns (sync 独占字段) 没变 → 不写 DDB
    assert "row" not in captured


# 这个 CR 让其余 3 个 dirty key (phase / endpoint_url / last_condition_message)
# 算完都不变, 用来隔离 status_detail 是否单独进入 dirty 判断:
#   - conditions=[Available=True] → derive_inference_phase 算出 "Running"
#   - 无 endpointUrl / invocationUrl / endpointArn → endpoint_url 落回 row 原值
#   - _collect_conditions 的 4 阶段骨架全是 Unknown 占位 (没有任何 status=True 的
#     已达成阶段) → last_condition_message 算出 None
_STABLE_CR = {
    "status": {
        "state": "Available",
        "conditions": [{"type": "Available", "status": "True"}],
    }
}


@pytest.mark.asyncio
async def test_status_detail_alone_skips_update(monkeypatch):
    """仅 status_detail 变化不再触发 crud.update — status_detail 归 informer,
    不在 _DIRTY_KEYS 里。

    row 把 phase / endpoint_url / last_condition_message 预设成 sync 算完不变的值,
    只留 status_detail 从旧值变新值。新语义下 sync 独占字段 (endpoint_url/alb_dns) 没变
    → crud.update 不应被调用。
    """
    captured = {}

    async def fake_update(db, row):
        captured["row"] = dict(row)
        return row

    monkeypatch.setattr(sync_mod.crud, "update", fake_update)

    row = {
        "id": "i2",
        "k8s_namespace": "ns",
        "k8s_endpoint_name": "ep",
        # sync 算完: phase="Available", endpoint_url=None, last_condition_message=None
        # → 这 3 个 dirty key 全不变
        "phase": "Available",
        "endpoint_url": None,
        "last_condition_message": None,
        # 唯一变化点: 旧 status_detail (与 sync 新写入的不同)
        "status_detail": {"state": "Pending", "conditions": [], "deploymentStatus": {}},
    }
    out, _conditions, _pods, _workloads = await sync_mod.sync_from_k8s(
        None, _FakeK8s(_STABLE_CR), row
    )

    # 先确认其余 3 个 dirty key 确实没被 sync 改动 (隔离前提成立)
    assert out["phase"] == "Available"
    assert out["endpoint_url"] is None
    assert out["last_condition_message"] is None
    # status_detail 被刷成新值 (in-memory 供响应)
    assert out["status_detail"] == {
        "state": "Available",
        "conditions": [{"type": "Available", "status": "True"}],
        "deploymentStatus": {},
    }
    # 关键断言: 仅 status_detail 变, sync 独占字段没变 → crud.update 不应被调用
    assert "row" not in captured


@pytest.mark.asyncio
async def test_no_dirty_key_changes_skips_update(monkeypatch):
    """反向: 所有 dirty key (含 status_detail) 都不变 → 不写 DDB。"""
    captured = {}

    async def fake_update(db, row):
        captured["row"] = dict(row)
        return row

    monkeypatch.setattr(sync_mod.crud, "update", fake_update)

    row = {
        "id": "i3",
        "k8s_namespace": "ns",
        "k8s_endpoint_name": "ep",
        "phase": "Available",
        "endpoint_url": None,
        "last_condition_message": None,
        # 预设成 sync 即将算出的同一个 status_detail → 完全不变
        "status_detail": {
            "state": "Available",
            "conditions": [{"type": "Available", "status": "True"}],
            "deploymentStatus": {},
        },
    }
    await sync_mod.sync_from_k8s(None, _FakeK8s(_STABLE_CR), row)

    # 全部 dirty key 不变 → crud.update 不应被调用
    assert "row" not in captured
