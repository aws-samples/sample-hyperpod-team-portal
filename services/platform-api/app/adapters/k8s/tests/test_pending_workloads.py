"""list_pending_workloads: raw GET Kueue visibility pendingworkloads。"""
from unittest.mock import AsyncMock

import pytest

from app.adapters.k8s.priority import PriorityMixin
from app.adapters.k8s.errors import K8sAPIError
from kubernetes_asyncio.client.exceptions import ApiException


class _M(PriorityMixin):
    def __init__(self):
        self._context = None
    async def _load_config(self):
        return None


@pytest.mark.asyncio
async def test_list_pending_workloads_parses_items(monkeypatch):
    sample = {"items": [
        {"metadata": {"ownerReferences": [{"name": "tg-q3"}]}, "positionInLocalQueue": 0},
        {"metadata": {"ownerReferences": [{"name": "tg-q4"}]}, "positionInLocalQueue": 1},
    ]}
    captured = {}

    class _FakeApi:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def call_api(self, resource_path, method, **kw):
            captured["path"] = resource_path
            captured["method"] = method
            return sample

    monkeypatch.setattr("app.adapters.k8s.priority.ApiClient", lambda: _FakeApi())
    out = await _M().list_pending_workloads("hyperpod-ns-team0", "hyperpod-ns-team0-localqueue")
    assert out == sample["items"]
    assert captured["method"] == "GET"
    assert "visibility.kueue.x-k8s.io/v1beta1" in captured["path"]
    assert "pendingworkloads" in captured["path"]
    assert "hyperpod-ns-team0-localqueue" in captured["path"]


@pytest.mark.asyncio
async def test_list_pending_workloads_api_error(monkeypatch):
    class _FakeApi:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def call_api(self, *a, **kw):
            raise ApiException(status=404, reason="NotFound")

    monkeypatch.setattr("app.adapters.k8s.priority.ApiClient", lambda: _FakeApi())
    with pytest.raises(K8sAPIError):
        await _M().list_pending_workloads("ns", "lq")
