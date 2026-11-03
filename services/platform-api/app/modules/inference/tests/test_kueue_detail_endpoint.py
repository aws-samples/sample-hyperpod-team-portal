"""推理 kueue-detail 端点: 2 跳实时查 Workload (最新 Pod → Workload), assert_ws_member 鉴权。"""
import pytest
from fastapi import HTTPException

from app.modules.inference.api import router as r


class _FakeK8s:
    async def list_pods_by_label_selector(self, ns, selector):
        return [
            {"metadata": {"uid": "old", "creationTimestamp": "2026-06-01T00:00:00Z"}},
            {"metadata": {"uid": "new", "creationTimestamp": "2026-06-02T00:00:00Z"}},
        ]

    async def list_workloads_by_job_uid(self, ns, uid):
        assert uid == "new"  # 取最新创建的 Pod
        return [{
            "metadata": {"creationTimestamp": "2026-06-02T10:00:00Z"},
            "status": {
                "conditions": [{"type": "Admitted", "status": "True"}],
                "admission": {"clusterQueue": "cq-1"},
            },
        }]


@pytest.mark.asyncio
async def test_kueue_detail_picks_latest_pod(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "i1", "workspace_id": "ws-1",
                "k8s_namespace": "ns1", "k8s_endpoint_name": "ep1"}

    async def fake_assert(ws_id, user):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_inference_kueue_detail("i1", k8s=_FakeK8s(), current_user={"id": "u"})
    assert out["conditions"][0]["type"] == "Admitted"
    assert out["admission"]["clusterQueue"] == "cq-1"


@pytest.mark.asyncio
async def test_kueue_detail_no_pod_empty(monkeypatch):
    class _Empty:
        async def list_pods_by_label_selector(self, ns, selector):
            return []

    async def fake_get(db, id_):
        return {"id": "i1", "workspace_id": "ws-1",
                "k8s_namespace": "ns1", "k8s_endpoint_name": "ep1"}

    async def fake_assert(ws_id, user):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    out = await r.get_inference_kueue_detail("i1", k8s=_Empty(), current_user={"id": "u"})
    assert out["conditions"] == []
    assert out["admission"] == {}


@pytest.mark.asyncio
async def test_kueue_detail_404(monkeypatch):
    async def fake_get(db, id_):
        return None

    monkeypatch.setattr(r.crud, "get", fake_get)
    with pytest.raises(HTTPException) as exc:
        await r.get_inference_kueue_detail("missing", k8s=_FakeK8s(), current_user={"id": "u"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_kueue_detail_forbidden(monkeypatch):
    async def fake_get(db, id_):
        return {"id": "i1", "workspace_id": "ws-1",
                "k8s_namespace": "ns1", "k8s_endpoint_name": "ep1"}

    async def fake_assert(ws_id, user):
        raise HTTPException(403, "not a member")

    monkeypatch.setattr(r.crud, "get", fake_get)
    monkeypatch.setattr(r, "assert_ws_member", fake_assert)

    with pytest.raises(HTTPException) as exc:
        await r.get_inference_kueue_detail("i1", k8s=_FakeK8s(), current_user={"id": "u"})
    assert exc.value.status_code == 403
