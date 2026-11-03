import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.adapters.k8s.workload import WorkloadMixin


class _Client(WorkloadMixin):
    _context = None

    async def _load_config(self):
        return None


@pytest.mark.asyncio
async def test_list_workloads_by_job_uid_filters_label():
    c = _Client()
    fake_resp = {"items": [{"metadata": {"name": "wl-1"}}]}
    api = MagicMock()
    co = MagicMock()
    co.list_namespaced_custom_object = AsyncMock(return_value=fake_resp)
    with patch("app.adapters.k8s.workload.ApiClient") as AC, \
         patch("app.adapters.k8s.workload.k8s_client.CustomObjectsApi", return_value=co):
        AC.return_value.__aenter__.return_value = api
        out = await c.list_workloads_by_job_uid("ns1", "uid-123")
    assert out == [{"metadata": {"name": "wl-1"}}]
    _, kwargs = co.list_namespaced_custom_object.call_args
    assert kwargs["label_selector"] == "kueue.x-k8s.io/job-uid=uid-123"


@pytest.mark.asyncio
async def test_list_workloads_empty():
    c = _Client()
    api = MagicMock()
    co = MagicMock()
    co.list_namespaced_custom_object = AsyncMock(return_value={})
    with patch("app.adapters.k8s.workload.ApiClient") as AC, \
         patch("app.adapters.k8s.workload.k8s_client.CustomObjectsApi", return_value=co):
        AC.return_value.__aenter__.return_value = api
        out = await c.list_workloads_by_job_uid("ns1", "uid-x")
    assert out == []
