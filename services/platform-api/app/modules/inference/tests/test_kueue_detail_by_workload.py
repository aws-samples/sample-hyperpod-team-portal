"""推理 kueue-detail-by-workload: 按 Workload 名精确查 conditions。"""
import pytest
from fastapi import HTTPException

from app.modules.inference.api import router as r


class _FakeK8s:
    """提供 list_workloads 的 fake K8s."""

    async def list_workloads(self, ns):
        return [
            {
                "metadata": {"name": "pod-ep-p1-h1"},
                "status": {
                    "conditions": [{"type": "Admitted", "status": "True"}],
                    "admission": {"clusterQueue": "cq"},
                },
            },
            {
                "metadata": {"name": "pod-ep-p2-h2"},
                "status": {"conditions": []},
            },
        ]


@pytest.mark.asyncio
async def test_kueue_detail_by_workload_returns_conditions(monkeypatch):
    """按 workload 名查到对应 conditions 和 admission."""
    row = {"id": "id1", "workspace_id": "ws1", "k8s_namespace": "ns1"}

    async def fake_get(db, id_):
        return row

    async def fake_assert(ws_id, user):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_inference_kueue_detail_by_workload(
        id="id1",
        workload="pod-ep-p1-h1",
        k8s=_FakeK8s(),
        current_user={"sub": "u"},
    )
    assert out["conditions"][0]["type"] == "Admitted"
    assert out["admission"]["clusterQueue"] == "cq"


@pytest.mark.asyncio
async def test_kueue_detail_by_workload_not_found_empty(monkeypatch):
    """找不到指定 workload 时返 empty."""
    row = {"id": "id1", "workspace_id": "ws1", "k8s_namespace": "ns1"}

    async def fake_get(db, id_):
        return row

    async def fake_assert(ws_id, user):
        return None

    class _EmptyK8s:
        async def list_workloads(self, ns):
            return []

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_inference_kueue_detail_by_workload(
        id="id1",
        workload="missing",
        k8s=_EmptyK8s(),
        current_user={"sub": "u"},
    )
    assert out == {"conditions": [], "admission": {}}


@pytest.mark.asyncio
async def test_kueue_detail_by_workload_404(monkeypatch):
    """推理不存在返 404."""

    async def fake_get(db, id_):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)

    with pytest.raises(HTTPException) as exc:
        await r.get_inference_kueue_detail_by_workload(
            id="missing",
            workload="wl",
            k8s=_FakeK8s(),
            current_user={"sub": "u"},
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_kueue_detail_by_workload_forbidden(monkeypatch):
    """非 ws 成员返 403."""
    row = {"id": "id1", "workspace_id": "ws1", "k8s_namespace": "ns1"}

    async def fake_get(db, id_):
        return row

    async def fake_assert(ws_id, user):
        raise HTTPException(403, "not a member")

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    with pytest.raises(HTTPException) as exc:
        await r.get_inference_kueue_detail_by_workload(
            id="id1",
            workload="wl",
            k8s=_FakeK8s(),
            current_user={"sub": "u"},
        )
    assert exc.value.status_code == 403
