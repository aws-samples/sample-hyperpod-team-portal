"""Workspace CR status → 开发机 phase 相关纯函数。

(历史: derive_devinstance_phase 曾把 CR 归一成 Creating / Running / Stopped /
Degraded / Queued / Error; 现 phase 全链路走 CR 原始值, 已废弃 — 见函数标注。)

kueue_status 三态 (queued/started/finished) 由 derive_dev_kueue_status 派生,
informer 写 (KS-1~6); 旧 derive_kueue_status (Pod 诊断 Queued/Error) 已删。
_refine_from_pod 仅供 derive_devinstance_phase (废弃纯函数 + test_phase.py) 用。
"""
from __future__ import annotations

from typing import Any


# Pod waiting reasons 归类为 Error 的集合
_ERROR_WAITING_REASONS = frozenset({
    "PostStartHookError",
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "InvalidImageName",
    "RunContainerError",
})


def derive_devinstance_phase(
    cr: dict[str, Any],
    pod: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """⚠️ 已废弃 (不再用于 DDB phase): phase 现全链路存 CR 原始值, sync 改用 informer
    同源拼接, 不再归一。本函数仅保留作纯函数 + test_phase.py
    守护, 勿重新当 phase 源引用 (会回归两套词表冲突)。

    返回 (phase, started_at)。

    started_at = Available condition status=True 时的 lastTransitionTime (开始运行时刻); 否则 None。
    优先级: Stopped > Available(Running) > Degraded > (Pod 细化) > Creating

    Args:
        cr: Workspace CR dict (含 status.conditions)。
        pod: 可选, K8s Pod dict (含 status.phase / status.conditions /
             status.containerStatuses)。当 CR 无法区分 "排队" 和 "启动失败" 时,
             用 Pod 状态细化。informer 场景不传 (保持纯 CR 逻辑);
             API detail/sync 场景传入。
    """
    conditions = (cr.get("status") or {}).get("conditions") or []
    by_type = {c.get("type"): c for c in conditions}

    def _true(t: str) -> bool:
        return (by_type.get(t) or {}).get("status") == "True"

    if _true("Stopped"):
        return "Stopped", None
    if _true("Available"):
        started = (by_type.get("Available") or {}).get("lastTransitionTime")
        return "Running", started
    if _true("Degraded"):
        return "Degraded", None

    # CR 既非 Available 也非 Degraded → "正在启动"。
    # 如果有 Pod 信息, 进一步区分: Queued / Error / Creating。
    if pod:
        phase = _refine_from_pod(pod)
        if phase:
            return phase, None

    return "Creating", None


def _refine_from_pod(pod: dict[str, Any]) -> str | None:
    """从 Pod 状态细化 phase。返回 None 表示无法判断 (保留 Creating)。"""
    pod_status = pod.get("status") or {}

    # 1. SchedulingGated → 排队 (Kueue 门控)
    pod_conditions = pod_status.get("conditions") or []
    for cond in pod_conditions:
        if cond.get("type") == "PodScheduled" and cond.get("status") == "False":
            reason = cond.get("reason", "")
            if reason == "SchedulingGated":
                return "Queued"

    # 2. 容器 waiting 状态 → Error
    for cs in pod_status.get("containerStatuses") or []:
        waiting = (cs.get("state") or {}).get("waiting") or {}
        reason = waiting.get("reason", "")
        if reason in _ERROR_WAITING_REASONS:
            return "Error"

    # 3. initContainerStatuses 也检查
    for cs in pod_status.get("initContainerStatuses") or []:
        waiting = (cs.get("state") or {}).get("waiting") or {}
        reason = waiting.get("reason", "")
        if reason in _ERROR_WAITING_REASONS:
            return "Error"

    return None


# 注: 旧 derive_dev_kueue_status / _pod_is_gated 已删 (kueue_status 改为镜像 Workload,
# 由 worker DevInstanceInformer 查 Workload 派生六态)。
