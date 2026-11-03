"""HyperPodPyTorchJob CR → 原始 phase 提取 (不再做 unified 归一/翻译)。

phase = status.conditions[] 中所有 status==True 的 type 用 "/" 拼接 (无 True → "")。
started_at: Running 优先否则 Created condition 的 lastTransitionTime。
ended_at: 终态 condition (Complete/Failed, status=True) 的 lastTransitionTime
  (CR status 无 completionTime, operator 不填)。多终态取最新。
保留 dataclass PhaseResult 供 informer 取值。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PhaseResult:
    phase: str
    started_at: str | None
    ended_at: str | None
    last_condition_message: str | None


# CR phase 优先级 (时间戳相同打破平局, 从高到低): 终态 > 运行/就绪 > 进行中 > 创建/挂起。
# 覆盖训练 (Failed/Complete/Running/Created/Suspended) 与开发机
# (Stopped/Degraded/Available/Initialized/Progressing) 两类 condition type。
_CR_PHASE_PRIORITY = (
    "Failed", "Complete", "Completed", "Succeeded", "Stopped", "Degraded",  # 终态类
    "Running", "Started", "PodsRunning", "Faulted", "Available",  # 运行/就绪类
    "Progressing", "Initialized", "Created", "Suspended",  # 进行中/创建/挂起
)


def pick_single_phase(cond_list: list[dict[str, Any]]) -> str:
    """从 True conditions 取单个: 先 lastTransitionTime 最新, 时间戳相同按 _CR_PHASE_PRIORITY。

    公共函数 (训练 derive_phase 与开发机 informer 共用), 故不加下划线前缀。
    无 True condition → 空串。
    """
    trues = [c for c in cond_list if c.get("status") == "True" and c.get("type")]
    if not trues:
        return ""

    def _rank(t: str) -> int:
        return _CR_PHASE_PRIORITY.index(t) if t in _CR_PHASE_PRIORITY else len(_CR_PHASE_PRIORITY)

    # 排序键: lastTransitionTime 降序(新在前) → 同时间按优先级(rank 小在前, 故取负配合 reverse)
    trues.sort(
        key=lambda c: (c.get("lastTransitionTime") or "", -_rank(c.get("type"))),
        reverse=True,
    )
    return trues[0].get("type")


def derive_phase(cr: dict[str, Any]) -> PhaseResult:
    status = cr.get("status") or {}
    cond_list = status.get("conditions") or []
    conds = {c.get("type"): c for c in cond_list}

    # 原始 phase: 取单个状态 (先 lastTransitionTime 最新, 时间戳相同按固定优先级)
    phase = pick_single_phase(cond_list)

    started = (conds.get("Running") or conds.get("Created") or {}).get(
        "lastTransitionTime"
    )
    # CR status 无 completionTime (operator 不填), 取终态 condition 的 lastTransitionTime.
    # 子串覆盖 Complete/Completed 与 Failed; 多终态取最新.
    ended = None
    for c in cond_list:
        t = c.get("type") or ""
        if c.get("status") == "True" and ("Complete" in t or "Failed" in t):
            lt = c.get("lastTransitionTime")
            if lt and (ended is None or lt > ended):
                ended = lt

    last_msg = cond_list[-1].get("message") if cond_list else None
    return PhaseResult(phase, started, ended, last_msg)


def derive_train_kueue_status(cr: dict[str, Any]) -> str:
    """训练 CR -> kueue_status 三态 (queued/started/finished)。纯 CR, 不查 Pod。

    优先级: Complete/Failed -> finished; 有任一启动 condition -> started;
    Suspended -> queued; 空 -> queued。
    """
    conds = (cr.get("status") or {}).get("conditions") or []
    true_types = {c.get("type") for c in conds if c.get("status") == "True"}
    # 终态用子串匹配: operator 终态 type 文档不一致 (Complete vs Completed),
    # 子串同时覆盖两者 (Completed 含 Complete)。Failed 同理。
    if any(t and ("Complete" in t or "Failed" in t) for t in true_types):
        return "finished"
    started_types = {"Started", "Running", "PodsRunning", "Created", "Faulted"}
    if true_types & started_types:
        return "started"
    if "Suspended" in true_types:
        return "queued"
    return "queued"
