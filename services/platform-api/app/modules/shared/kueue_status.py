"""Kueue 六态集中定义 + 活跃/终态判定 + 从 Workload 派生状态。

六态直接用 Kueue Workload condition type 名。所有"活跃/终态/排队"判定
一律引用此模块, 禁止散落字符串比较 (大小写失配会静默恒 False)。
"""
from __future__ import annotations

from typing import Any

# ── 六态 (Workload condition type 名, 首字母大写) ──
KUEUE_QUEUED = "Queued"
KUEUE_QUOTA_RESERVED = "QuotaReserved"
KUEUE_ADMITTED = "Admitted"
KUEUE_PODS_READY = "PodsReady"
KUEUE_EVICTED = "Evicted"
KUEUE_FINISHED = "Finished"

# 终态集: 只有 Finished (Evicted 是中间态 — 被抢占踢回排队, 仍算活跃)
TERMINAL_STATES = {KUEUE_FINISHED}

# 活跃集: 非终态 (前 5 态全活跃, 含 Evicted)
ACTIVE_STATES = {
    KUEUE_QUEUED, KUEUE_QUOTA_RESERVED, KUEUE_ADMITTED,
    KUEUE_PODS_READY, KUEUE_EVICTED,
}

# 存量旧小写三态 (迁移期读兼容)
_LEGACY_FINISHED = "finished"

# 取态固定优先级 (从高到低, 取第一个 status==True 的 condition)
_PRIORITY = (
    KUEUE_FINISHED, KUEUE_EVICTED, KUEUE_PODS_READY,
    KUEUE_ADMITTED, KUEUE_QUOTA_RESERVED,
)


def is_active(kueue_status: str | None) -> bool:
    """活跃判定 (含存量兼容): 有值且不是任一种 finished。"""
    if not kueue_status:
        return False
    return kueue_status not in TERMINAL_STATES and kueue_status != _LEGACY_FINISHED


def is_terminal(kueue_status: str | None) -> bool:
    """终态判定 (含存量兼容): Finished 或旧小写 finished。Evicted 不算终态。"""
    return kueue_status in TERMINAL_STATES or kueue_status == _LEGACY_FINISHED


def derive_kueue_status_from_workload(workload: dict[str, Any] | None) -> str | None:
    """从单个 Workload 派生六态。纯固定优先级 (不看 lastTransitionTime, 实证时间戳常相同)。

    - workload=None → 返回 None (调用方按 CR phase 决定 Finished 或保持上次值)
    - 有 condition status==True → 按 _PRIORITY 取最高的那个 type
    - 全 False / 缺失 (排队中) → 兜底 Queued
    """
    if workload is None:
        return None
    conds = ((workload.get("status") or {}).get("conditions")) or []
    true_types = {
        c.get("type") for c in conds if c.get("status") == "True" and c.get("type")
    }
    for t in _PRIORITY:
        if t in true_types:
            return t
    return KUEUE_QUEUED


def _last_transition_time(obj: dict[str, Any]) -> str:
    """取对象 status.conditions 中最大的 lastTransitionTime (ISO8601, 字典序=时间序)。

    Pod: status.conditions[].lastTransitionTime
    Workload: status.conditions[].lastTransitionTime
    无 conditions 或字段缺失 → 回退 metadata.creationTimestamp。
    """
    conds = ((obj.get("status") or {}).get("conditions")) or []
    times = [
        c.get("lastTransitionTime") or ""
        for c in conds
        if c.get("lastTransitionTime")
    ]
    if times:
        return max(times)
    return (obj.get("metadata") or {}).get("creationTimestamp") or ""


def pick_latest_pod(pods: list[dict[str, Any]]) -> dict[str, Any] | None:
    """多 Pod/Workload 取最近状态变化的 (conditions.lastTransitionTime 最大)。

    多 replica 下选状态最新变化的 Pod, 最能反映当前正在发生的事。
    稳定态时所有 Pod 时间相同, 选哪个无差别。
    无 conditions 时回退 creationTimestamp (兼容)。
    Pod 与 Workload 都有 status.conditions, 此函数对两者通用。
    """
    if not pods:
        return None
    return max(pods, key=_last_transition_time)


# 组件间"取最差"进展 rank (越小越差; 取 min)。用于 llm-d: LWS 与 gateway 都好才能服务
# (组件 AND 语义)。⚠️ 与 controller 内 aggregateKueueBest (同组件多副本取最好) 方向相反。
# Evicted 排低位 (比 Admitted 差): 被驱逐重新排队, 语义上比已准入差, 显示"被驱逐"使问题可见。
_WORST_RANK = {
    KUEUE_QUEUED: 0, KUEUE_EVICTED: 1, KUEUE_QUOTA_RESERVED: 2,
    KUEUE_ADMITTED: 3, KUEUE_PODS_READY: 4, KUEUE_FINISHED: 5,
}


def worst_kueue_status(a: str | None, b: str | None) -> str | None:
    """两个组件状态取最差 (进展最小)。

    - 任一为 None / 不在 rank 表 (老数据/legacy/未知) → 视为无约束, 回落另一个已知值。
    - 都 None → None。
    llm-d 用: worst(kueue_status, gateway_kueue_status)。半删态 (一方 Finished 一方
    Admitted) → 取 Admitted (非终态), 使 is_terminal 过滤不误杀、泄漏可见。
    """
    ra = _WORST_RANK.get(a) if a is not None else None
    rb = _WORST_RANK.get(b) if b is not None else None
    if ra is None and rb is None:
        return a if a is not None else b
    if ra is None:
        return b
    if rb is None:
        return a
    return a if ra <= rb else b
