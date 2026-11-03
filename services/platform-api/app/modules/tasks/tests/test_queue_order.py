"""get_queue_order: 解析 visibility items → {cr_name: {position, workloads}}; 查失败→{}。"""
from unittest.mock import AsyncMock

import pytest

from app.modules.tasks import service


@pytest.mark.asyncio
async def test_get_queue_order_maps_name_to_position(monkeypatch):
    items = [
        {"metadata": {"name": "tg-q3-wl", "ownerReferences": [{"name": "tg-q3"}]}, "positionInLocalQueue": 0, "priority": 80},
        # 缺 priority 字段 → 回落 0 (测容错)
        {"metadata": {"name": "tg-q4-wl", "ownerReferences": [{"name": "tg-q4"}]}, "positionInLocalQueue": 1},
        {"metadata": {"name": "orphan-wl", "ownerReferences": []}, "positionInLocalQueue": 2},
        {"metadata": {"name": "tg-q6-wl", "ownerReferences": [{"name": "tg-q6"}]}},
    ]
    k8s = AsyncMock()
    k8s.list_pending_workloads = AsyncMock(return_value=items)
    k8s.list_podcliquesets = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "_ws_namespace", AsyncMock(return_value="hyperpod-ns-team0"))
    out = await service.get_queue_order("ws-1", k8s)
    assert out == {
        "tg-q3": {"position": 0, "workloads": [{"name": "tg-q3-wl", "position": 0, "priority": 80}]},
        "tg-q4": {"position": 1, "workloads": [{"name": "tg-q4-wl", "position": 1, "priority": 0}]},
    }
    k8s.list_pending_workloads.assert_awaited_once_with(
        "hyperpod-ns-team0", "hyperpod-ns-team0-localqueue"
    )
    # 这些 owner 无 kind (非 Pod) → 不触发 dynamo PCS list。
    k8s.list_podcliquesets.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_queue_order_failure_returns_empty(monkeypatch):
    k8s = AsyncMock()
    k8s.list_pending_workloads = AsyncMock(side_effect=RuntimeError("kueue down"))
    monkeypatch.setattr(service, "_ws_namespace", AsyncMock(return_value="ns"))
    out = await service.get_queue_order("ws-1", k8s)
    assert out == {}


@pytest.mark.asyncio
async def test_get_queue_order_one_task_multi_workload(monkeypatch):
    lws = "bob-3-replica-65q1m7bbzl-multi"
    items = [
        {"metadata": {"name": "wl-g1", "ownerReferences": [{"kind": "LeaderWorkerSet", "name": lws}]}, "positionInLocalQueue": 2, "priority": 0},
        {"metadata": {"name": "wl-g0", "ownerReferences": [{"kind": "LeaderWorkerSet", "name": lws}]}, "positionInLocalQueue": 0, "priority": 0},
        {"metadata": {"name": "wl-g2", "ownerReferences": [{"kind": "LeaderWorkerSet", "name": lws}]}, "positionInLocalQueue": 1, "priority": 0},
    ]
    k8s = AsyncMock()
    k8s.list_pending_workloads = AsyncMock(return_value=items)
    k8s.list_podcliquesets = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "_ws_namespace", AsyncMock(return_value="ns"))
    out = await service.get_queue_order("ws-1", k8s)
    entry = out["bob-3-replica-65q1m7bbzl"]
    assert entry["position"] == 0
    assert entry["workloads"] == [
        {"name": "wl-g0", "position": 0, "priority": 0},
        {"name": "wl-g2", "position": 1, "priority": 0},
        {"name": "wl-g1", "position": 2, "priority": 0},
    ]


# --- _owner_to_k8s_name: 三类任务 owner → 任务 CR name ---
# 真集群实证 (2026-06-23, hyperpod-ns-demo): pendingworkloads owner
# 训练 ownerKind=HyperPodPyTorchJob (name 即 CR), 开发机/推理 ownerKind=Pod
# (Pod 名 = <deployment>-<rs哈希>-<pod后缀>, 开发机 deployment 带 workspace- 前缀)。


@pytest.mark.parametrize(
    "kind,name,expected",
    [
        # 训练: CR 直接是 owner, name 即 k8s_name
        ("HyperPodPyTorchJob", "bob-02-copy-15zh415c6t", "bob-02-copy-15zh415c6t"),
        # 推理: Pod, 去掉末尾两段 (RS 哈希 + Pod 后缀)
        (
            "Pod",
            "bob-queue-copy-k03ftugdvw-7466995d7b-zhl24",
            "bob-queue-copy-k03ftugdvw",
        ),
        # 开发机: Pod, 去掉末尾两段后再去 workspace- 前缀
        (
            "Pod",
            "workspace-bob-queue-dev-4fc463-5884794989-p5nbz",
            "bob-queue-dev-4fc463",
        ),
    ],
)
def test_owner_to_k8s_name(kind, name, expected):
    assert service._owner_to_k8s_name(kind, name) == expected


def test_owner_to_k8s_name_dynamo_pcs_prefix():
    """dynamo Pod 名切不出 DGD 名 → 按 PCS 名前缀匹配取 DGD label 值; 未命中回落 rsplit。

    真集群实证 (2026-07-16): CR 名 > 24 字符时 PCS 名被截断 (PCS != DGD), 故必须
    靠 PCS 的 label 值还原完整 DGD 名, 且用前缀匹配 owner Pod 名。
    """
    # 短名: PCS 名 = DGD 名
    pcs_map = {
        "test-multi-02-e588qlgfyr": "test-multi-02-e588qlgfyr",
        # 长名: PCS 名被截断 (24 字符 + 哈希), DGD 名靠 label 还原
        "bob-test-multi-04-copy-g-b7b3": "bob-test-multi-04-copy-g2y3vnvqtr",
    }
    # 短名 Pod 前缀命中
    assert (
        service._owner_to_k8s_name(
            "Pod", "test-multi-02-e588qlgfyr-0-worker-0-worker-ldr-p97sv", pcs_map
        )
        == "test-multi-02-e588qlgfyr"
    )
    # 长名 (截断 PCS) Pod 前缀命中 → 还原完整 DGD 名
    assert (
        service._owner_to_k8s_name(
            "Pod", "bob-test-multi-04-copy-g-b7b3-0-worker-0-worker-wkr-2x96t", pcs_map
        )
        == "bob-test-multi-04-copy-g2y3vnvqtr"
    )
    # 未命中任何 PCS: 回落 rsplit (推理/开发机路径不受影响)
    assert (
        service._owner_to_k8s_name(
            "Pod", "bob-queue-copy-k03ftugdvw-7466995d7b-zhl24", pcs_map
        )
        == "bob-queue-copy-k03ftugdvw"
    )


def test_owner_to_k8s_name_dynamo_longest_prefix_wins():
    """两个 PCS 名一个是另一个前缀时, 取最长匹配 (最精确) 防误配。"""
    pcs_map = {
        "app-01": "app-01-dgd",
        "app-01-copy": "app-01-copy-dgd",
    }
    # Pod 属 app-01-copy, 不应被更短的 app-01 套住
    assert (
        service._owner_to_k8s_name(
            "Pod", "app-01-copy-0-worker-0-worker-ldr-xyz", pcs_map
        )
        == "app-01-copy-dgd"
    )


@pytest.mark.asyncio
async def test_get_queue_order_three_kinds(monkeypatch):
    """三类真实样本端到端: 训练/推理/开发机都能映射回各自 k8s_name。"""
    items = [
        {
            "metadata": {
                "name": "dev-wl",
                "ownerReferences": [
                    {"kind": "Pod", "name": "workspace-bob-queue-dev-4fc463-5884794989-p5nbz"}
                ],
            },
            "positionInLocalQueue": 0,
            "priority": 50,
        },
        {
            "metadata": {
                "name": "train-wl",
                "ownerReferences": [
                    {"kind": "HyperPodPyTorchJob", "name": "bob-02-copy-15zh415c6t"}
                ],
            },
            "positionInLocalQueue": 1,
            "priority": 80,
        },
        {
            "metadata": {
                "name": "inf-wl",
                "ownerReferences": [
                    {"kind": "Pod", "name": "bob-queue-copy-k03ftugdvw-7466995d7b-zhl24"}
                ],
            },
            "positionInLocalQueue": 2,
            "priority": 0,
        },
    ]
    k8s = AsyncMock()
    k8s.list_pending_workloads = AsyncMock(return_value=items)
    k8s.list_podcliquesets = AsyncMock(return_value=[])  # 无 dynamo PCS
    monkeypatch.setattr(service, "_ws_namespace", AsyncMock(return_value="ns"))
    out = await service.get_queue_order("ws-1", k8s)
    assert out == {
        "bob-queue-dev-4fc463": {
            "position": 0,
            "workloads": [{"name": "dev-wl", "position": 0, "priority": 50}],
        },
        "bob-02-copy-15zh415c6t": {
            "position": 1,
            "workloads": [{"name": "train-wl", "position": 1, "priority": 80}],
        },
        "bob-queue-copy-k03ftugdvw": {
            "position": 2,
            "workloads": [{"name": "inf-wl", "position": 2, "priority": 0}],
        },
    }
    # 有 Pod owner (推理/开发机) → 触发一次 dynamo PCS list; 表空 → 全部回落 rsplit。
    k8s.list_podcliquesets.assert_awaited_once_with("ns")


def _pcs(name: str, dgd: str) -> dict:
    return {"metadata": {"name": name, "labels": {service._DYNAMO_DGD_LABEL: dgd}}}


@pytest.mark.asyncio
async def test_get_queue_order_dynamo_multi_workload_min(monkeypatch):
    """dynamo 一任务多 Workload (多 Pod owner, position 散布) → 按 PCS 前缀归一同一 DGD 取 min。"""
    dgd = "bob-multi-replica-3-wc37dm2hp6"
    pcs = "bob-multi-replica-3-wc37-c08d"  # 长名截断后的 PCS 名 (Pod 前缀)
    p1 = f"{pcs}-0-worker-0-worker-wkr-aaa"
    p2 = f"{pcs}-0-worker-0-worker-ldr-bbb"
    p3 = f"{pcs}-0-worker-0-worker-wkr-ccc"
    items = [
        {"metadata": {"name": "wl-1", "ownerReferences": [{"kind": "Pod", "name": p1}]}, "positionInLocalQueue": 5, "priority": 0},
        {"metadata": {"name": "wl-2", "ownerReferences": [{"kind": "Pod", "name": p2}]}, "positionInLocalQueue": 2, "priority": 0},
        {"metadata": {"name": "wl-3", "ownerReferences": [{"kind": "Pod", "name": p3}]}, "positionInLocalQueue": 8, "priority": 0},
    ]
    k8s = AsyncMock()
    k8s.list_pending_workloads = AsyncMock(return_value=items)
    k8s.list_podcliquesets = AsyncMock(return_value=[_pcs(pcs, dgd)])
    monkeypatch.setattr(service, "_ws_namespace", AsyncMock(return_value="ns"))
    out = await service.get_queue_order("ws-1", k8s)
    # 三个 Workload 前缀归一到同一 DGD (label 还原完整名), 取最靠前 position (2), 明细全透传升序
    assert out == {
        dgd: {
            "position": 2,
            "workloads": [
                {"name": "wl-2", "position": 2, "priority": 0},
                {"name": "wl-1", "position": 5, "priority": 0},
                {"name": "wl-3", "position": 8, "priority": 0},
            ],
        }
    }


@pytest.mark.asyncio
async def test_get_queue_order_dynamo_pcs_list_fail_degrades(monkeypatch):
    """dynamo PCS list 失败 → 空映射, Pod owner 回落 rsplit, 不抛不阻塞。"""
    pod = "bob-multi-replica-3-wc37-c08d-0-worker-0-worker-wkr-aaa"
    items = [
        {"metadata": {"name": "wl-x", "ownerReferences": [{"kind": "Pod", "name": pod}]}, "positionInLocalQueue": 0, "priority": 0},
    ]
    k8s = AsyncMock()
    k8s.list_pending_workloads = AsyncMock(return_value=items)
    k8s.list_podcliquesets = AsyncMock(side_effect=RuntimeError("pcs down"))
    monkeypatch.setattr(service, "_ws_namespace", AsyncMock(return_value="ns"))
    out = await service.get_queue_order("ws-1", k8s)
    # 映射表空 → 回落 rsplit('-',2)[0] (对 dynamo 名不准, 但不崩; 属降级可接受)
    assert out == {
        pod.rsplit("-", 2)[0]: {
            "position": 0,
            "workloads": [{"name": "wl-x", "position": 0, "priority": 0}],
        }
    }


# --- llmd owner → 裸任务名 ---
def test_owner_to_k8s_name_llmd_lws():
    # LWS Workload: owner=LeaderWorkerSet/<task>-multi → strip -multi → <task>
    assert service._owner_to_k8s_name(
        "LeaderWorkerSet", "bob-3-replica-65q1m7bbzl-multi", None
    ) == "bob-3-replica-65q1m7bbzl"


def test_owner_to_k8s_name_llmd_gateway_pod():
    # gateway Workload: owner=Pod/<task>-gateway-<rs>-<suf> → 截到 <task> → <task>
    assert service._owner_to_k8s_name(
        "Pod", "bob-3-replica-65q1m7bbzl-gateway-859b5c79b4-gm6sk", None
    ) == "bob-3-replica-65q1m7bbzl"
