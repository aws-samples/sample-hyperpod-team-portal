"""RayJob kueue-detail 端点: 1 跳实时查 Workload (CR uid = job-uid, 同训练), assert_ws_member 鉴权。

status-detail 端点的测试见同目录 test_status_detail_endpoint.py。
"""
import pytest
from fastapi import HTTPException

from app.modules.rayjob.api import router as r


class _FakeK8s:
    async def get_rayjob(self, ns, name):
        return {"metadata": {"uid": "cr-uid-1"}}

    async def list_workloads_by_job_uid(self, ns, uid):
        assert uid == "cr-uid-1"
        return [{
            "metadata": {"creationTimestamp": "2026-07-22T10:00:00Z"},
            "status": {
                "conditions": [{"type": "Admitted", "status": "True",
                                "message": "Admitted by CQ"}],
                "admission": {"clusterQueue": "cq-ray"},
            },
        }]


@pytest.mark.asyncio
async def test_kueue_detail_returns_conditions_and_admission(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "ray1", "workspace_id": "ws-1",
                "k8s_namespace": "ns1", "k8s_cr_name": "cr1"}

    async def fake_assert(ws_id, user):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_rayjob_kueue_detail("ray1", k8s=_FakeK8s(), current_user={"id": "u"})
    assert out["conditions"][0]["type"] == "Admitted"
    assert out["admission"]["clusterQueue"] == "cq-ray"


@pytest.mark.asyncio
async def test_kueue_detail_no_workload_empty(monkeypatch):
    class _Empty:
        async def get_rayjob(self, ns, name):
            return {"metadata": {"uid": "u1"}}

        async def list_workloads_by_job_uid(self, ns, uid):
            return []

    async def fake_get(db, id_):
        return {"id": "ray1", "workspace_id": "ws-1",
                "k8s_namespace": "ns1", "k8s_cr_name": "cr1"}

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", lambda ws, u: _noop())

    out = await r.get_rayjob_kueue_detail("ray1", k8s=_Empty(), current_user={"id": "u"})
    assert out["conditions"] == []
    assert out["admission"] == {}


@pytest.mark.asyncio
async def test_kueue_detail_404(monkeypatch):
    async def fake_get(db, id_):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    with pytest.raises(HTTPException) as exc:
        await r.get_rayjob_kueue_detail("missing", k8s=_FakeK8s(), current_user={"id": "u"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_kueue_detail_forbidden(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "ray1", "workspace_id": "ws-1",
                "k8s_namespace": "ns1", "k8s_cr_name": "cr1"}

    async def fake_assert(ws_id, user):
        raise HTTPException(403, "not a member")

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    with pytest.raises(HTTPException) as exc:
        await r.get_rayjob_kueue_detail("ray1", k8s=_FakeK8s(), current_user={"id": "u"})
    assert exc.value.status_code == 403


async def _noop():
    return None
