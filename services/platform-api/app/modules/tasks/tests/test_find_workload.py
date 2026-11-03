"""find_workload_for_task: 三类通用 uid-based 反查 Workload。

背景: 原 find_workload_by_owner 用 ownerReferences[].name == cr_name 精确匹配,
只对训练成立 (训练 Workload 直接 owned by CR)。开发机/推理的 Workload owned by Pod
(owner.name 带 hash, 对不上 cr_name) → 404。

真集群实证 (2026-06-11) 三类关联链:
  - 训练:   Workload.label[job-uid] == HyperPodPyTorchJob CR.uid
  - 开发机: Workload.label[job-uid] == Pod.uid; Pod 靠 label workspace.jupyter.org/workspace-name==cr_name 找
  - 推理:   Workload.label[job-uid] == Pod.uid; Pod 靠 label app==cr_name 找
统一: 先按 type 拿到 "Kueue job 对象" 的 uid, 再用 label_selector job-uid=<uid> 精确查 Workload。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.k8s.priority import PriorityMixin


class _Client(PriorityMixin):
    async def _load_config(self):
        return None


def _patched(fake_co):
    return (
        patch("app.adapters.k8s.priority.ApiClient"),
        patch(
            "app.adapters.k8s.priority.k8s_client.CustomObjectsApi",
            return_value=fake_co,
        ),
    )


@pytest.mark.asyncio
async def test_train_uses_cr_uid():
    fake_co = MagicMock()
    # get CR → uid
    fake_co.get_namespaced_custom_object = AsyncMock(
        return_value={"metadata": {"uid": "cr-uid-1"}}
    )
    # list workload by label_selector → 命中
    fake_co.list_namespaced_custom_object = AsyncMock(
        return_value={"items": [{"metadata": {"name": "wl-train-1"}}]}
    )
    p1, p2 = _patched(fake_co)
    with p1, p2:
        wl = await _Client().find_workload_for_task(
            "ns-1", "train", "ddp-bob-queue-b424ec"
        )
    assert wl["metadata"]["name"] == "wl-train-1"
    # 训练: 直接 get CR 拿 uid
    fake_co.get_namespaced_custom_object.assert_awaited_once()
    # workload 查询用了 label_selector job-uid=cr-uid-1
    _, kwargs = fake_co.list_namespaced_custom_object.call_args
    assert kwargs.get("label_selector") == "kueue.x-k8s.io/job-uid=cr-uid-1"


@pytest.mark.asyncio
async def test_dev_uses_pod_uid_via_workspace_name_label():
    fake_co = MagicMock()
    # Pod 查询走 CoreV1Api.list_namespaced_pod; Workload 查询走 CustomObjectsApi。
    fake_co.list_namespaced_pod = AsyncMock(
        return_value=MagicMock(
            items=[MagicMock(metadata=MagicMock(uid="pod-uid-9"))]
        )
    )
    fake_co.list_namespaced_custom_object = AsyncMock(
        return_value={"items": [{"metadata": {"name": "wl-dev-1"}}]}
    )
    with patch("app.adapters.k8s.priority.ApiClient"), patch(
        "app.adapters.k8s.priority.k8s_client.CustomObjectsApi", return_value=fake_co
    ), patch(
        "app.adapters.k8s.priority.k8s_client.CoreV1Api", return_value=fake_co
    ):
        wl = await _Client().find_workload_for_task(
            "ns-1", "dev", "bob-dev-05-aba939"
        )
    assert wl["metadata"]["name"] == "wl-dev-1"
    # Pod 查询用 workspace-name label
    _, pod_kwargs = fake_co.list_namespaced_pod.call_args
    assert (
        pod_kwargs.get("label_selector")
        == "workspace.jupyter.org/workspace-name=bob-dev-05-aba939"
    )


@pytest.mark.asyncio
async def test_inference_uses_pod_uid_via_app_label():
    fake_co = MagicMock()
    fake_co.list_namespaced_pod = AsyncMock(
        return_value=MagicMock(
            items=[MagicMock(metadata=MagicMock(uid="pod-uid-7"))]
        )
    )
    fake_co.list_namespaced_custom_object = AsyncMock(
        return_value={"items": [{"metadata": {"name": "wl-inf-1"}}]}
    )
    with patch("app.adapters.k8s.priority.ApiClient"), patch(
        "app.adapters.k8s.priority.k8s_client.CustomObjectsApi", return_value=fake_co
    ), patch(
        "app.adapters.k8s.priority.k8s_client.CoreV1Api", return_value=fake_co
    ):
        wl = await _Client().find_workload_for_task("ns-1", "inference", "aaa-3606a5")
    assert wl["metadata"]["name"] == "wl-inf-1"
    _, pod_kwargs = fake_co.list_namespaced_pod.call_args
    assert pod_kwargs.get("label_selector") == "app=aaa-3606a5"


@pytest.mark.asyncio
async def test_returns_none_when_no_pod():
    fake_co = MagicMock()
    fake_co.list_namespaced_pod = AsyncMock(return_value=MagicMock(items=[]))
    with patch("app.adapters.k8s.priority.ApiClient"), patch(
        "app.adapters.k8s.priority.k8s_client.CustomObjectsApi", return_value=fake_co
    ), patch(
        "app.adapters.k8s.priority.k8s_client.CoreV1Api", return_value=fake_co
    ):
        wl = await _Client().find_workload_for_task("ns-1", "dev", "missing")
    assert wl is None


@pytest.mark.asyncio
async def test_unknown_type_raises():
    from app.adapters.k8s.errors import K8sAPIError

    with pytest.raises(K8sAPIError):
        await _Client().find_workload_for_task("ns-1", "nonsense", "x")
