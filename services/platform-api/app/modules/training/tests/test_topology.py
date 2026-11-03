"""resolve_topology_levels 测试.

两跳链路用 fake k8s: flavor → topologyName → Topology.levels。
覆盖空列表四种来源 + 倒序 + display_name 回落。
"""

from __future__ import annotations

import pytest

from app.modules.training.orchestration.topology import resolve_topology_levels

_L1 = "topology.k8s.aws/network-node-layer-1"
_L2 = "topology.k8s.aws/network-node-layer-2"
_L3 = "topology.k8s.aws/network-node-layer-3"
_ZONE = "topology.k8s.aws/zone-id"


class _FakeK8s:
    """按 name 返预置的 flavor / topology; 缺就返 None (模拟 404)。"""

    def __init__(
        self, flavors: dict | None = None, topologies: dict | None = None
    ):
        self._flavors = flavors or {}
        self._topologies = topologies or {}

    async def get_resource_flavor(self, name: str):
        return self._flavors.get(name)

    async def get_topology(self, name: str):
        return self._topologies.get(name)


def _topo(*labels: str) -> dict:
    return {"spec": {"levels": [{"nodeLabel": lbl} for lbl in labels]}}


@pytest.mark.asyncio
async def test_three_levels_returned_fine_to_coarse():
    """多级 → 倒序返回 (层号大的在前), depth 是声明位置。"""
    k8s = _FakeK8s(
        flavors={"ml.p5.48xlarge": {"spec": {"topologyName": "hyperpod"}}},
        topologies={"hyperpod": _topo(_L1, _L2, _L3)},
    )
    out = await resolve_topology_levels(k8s, "ml.p5.48xlarge")
    assert [lv.node_label for lv in out] == [_L3, _L2, _L1]
    assert [lv.depth for lv in out] == [3, 2, 1]
    assert out[0].display_name == "layer-3"


@pytest.mark.asyncio
async def test_single_level_returns_empty():
    """只有一级 → [] (唯一选择等于不选, 前端置灰)。"""
    k8s = _FakeK8s(
        flavors={
            "ml.g6.12xlarge": {"spec": {"topologyName": "hyperpod-default"}}
        },
        topologies={"hyperpod-default": _topo(_ZONE)},
    )
    assert await resolve_topology_levels(k8s, "ml.g6.12xlarge") == []


@pytest.mark.asyncio
async def test_no_flavor_returns_empty():
    """机型没有对应 flavor (不在配额里) → [], 不抛错。"""
    assert await resolve_topology_levels(_FakeK8s(), "ml.nope.1xlarge") == []


@pytest.mark.asyncio
async def test_flavor_without_topology_name_returns_empty():
    """flavor 存在但 topologyName 为空 (add-on 还没 patch 上) → []。"""
    k8s = _FakeK8s(flavors={"ml.new.1xlarge": {"spec": {}}})
    assert await resolve_topology_levels(k8s, "ml.new.1xlarge") == []


@pytest.mark.asyncio
async def test_topology_missing_returns_empty():
    """flavor 指向一个不存在的 Topology → []。"""
    k8s = _FakeK8s(flavors={"ml.x.1xlarge": {"spec": {"topologyName": "ghost"}}})
    assert await resolve_topology_levels(k8s, "ml.x.1xlarge") == []


@pytest.mark.asyncio
async def test_unknown_label_falls_back_to_raw():
    """未知 label 的 display_name 回落原值 (不显示空白)。"""
    k8s = _FakeK8s(
        flavors={"ml.future.1xlarge": {"spec": {"topologyName": "future"}}},
        topologies={"future": _topo(_L1, "topology.k8s.aws/brand-new-layer")},
    )
    out = await resolve_topology_levels(k8s, "ml.future.1xlarge")
    assert out[0].node_label == "topology.k8s.aws/brand-new-layer"
    assert out[0].display_name == "topology.k8s.aws/brand-new-layer"
