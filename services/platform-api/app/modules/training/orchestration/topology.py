"""按实例类型解析可用的 Kueue 拓扑层级.

    instance_type → ResourceFlavor.spec.topologyName → Topology.spec.levels[].nodeLabel

levels 声明顺序是粗→细 (Kueue 约定), 层号越大越靠近实例 → 返回时倒序, 延迟低的在前。

空列表 = 无可选: 查不到 flavor / 未绑 topologyName / 查不到 Topology / 只有一级
(唯一选择等于不选)。

flavor 名 == instance_type 是 add-on 的建法约定不是 Kueue 强制。若 flavor 改名,
这里改成按 .spec.nodeLabels 的 node.kubernetes.io/instance-type 反查。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.training.api.schemas import TopologyLevel

logger = get_logger(__name__)

# 显示名美化表, 不参与校验
_LEVEL_NAMES = {
    "topology.k8s.aws/ultraserver-id": "UltraServer",
    "topology.k8s.aws/network-node-layer-4": "layer-4",
    "topology.k8s.aws/network-node-layer-3": "layer-3",
    "topology.k8s.aws/network-node-layer-2": "layer-2",
    "topology.k8s.aws/network-node-layer-1": "layer-1",
}
# 需按语言翻译的层级 → 文案 key (请求期再取, 不在模块级调 t())
_LEVEL_NAME_KEYS = {
    "topology.k8s.aws/zone-id": "training.topology_level_zone",
    "kubernetes.io/hostname": "training.topology_level_node",
}


def _display_name(node_label: str) -> str:
    """已知 label 给显示名 (随请求语言), 未知回落原 label。"""
    key = _LEVEL_NAME_KEYS.get(node_label)
    if key:
        return t(key)
    return _LEVEL_NAMES.get(node_label, node_label)


async def resolve_topology_levels(
    k8s: Any, instance_type: str
) -> list[TopologyLevel]:
    """该机型可用的拓扑层级, 由细到粗。查不到或只有一级返 `[]`。"""
    flavor = await k8s.get_resource_flavor(instance_type)
    if not flavor:
        logger.debug("topology.no_flavor instance_type=%s", instance_type)
        return []

    topo_name = ((flavor.get("spec") or {}).get("topologyName")) or ""
    if not topo_name:
        logger.debug("topology.flavor_unbound instance_type=%s", instance_type)
        return []

    topo = await k8s.get_topology(topo_name)
    levels = ((topo or {}).get("spec") or {}).get("levels") or []
    node_labels = [
        lv["nodeLabel"] for lv in levels if (lv or {}).get("nodeLabel")
    ]
    if len(node_labels) <= 1:
        logger.debug(
            "topology.single_level instance_type=%s topology=%s count=%d",
            instance_type, topo_name, len(node_labels),
        )
        return []

    out = [
        TopologyLevel(
            node_label=label,
            depth=idx,
            display_name=_display_name(label),
        )
        for idx, label in enumerate(node_labels, start=1)
    ]
    out.reverse()
    return out
