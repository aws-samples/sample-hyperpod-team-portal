"""Pod 状态聚合 (kubectl get pod 风格): ready / status / restarts。

phase 不够 — phase=Running 时容器可能 CrashLoopBackOff。kubectl 显示的 STATUS 来自
containerStatuses 的 waiting/terminated reason, 比 phase 准。这里复刻 kubectl 的聚合。
训练/推理 _pod_summary 共用。
"""

from __future__ import annotations

from typing import Any


def summarize_pod(p: dict[str, Any]) -> dict[str, Any]:
    """从 pod dict 算 ready('1/2') / status('CrashLoopBackOff') / restarts(int)。"""
    status_ = p.get("status") or {}
    spec = p.get("spec") or {}
    cs_list = status_.get("container_statuses") or status_.get("containerStatuses") or []

    total = len(spec.get("containers") or []) or len(cs_list)
    ready = sum(1 for c in cs_list if c.get("ready"))
    restarts = sum(int(c.get("restart_count") or c.get("restartCount") or 0) for c in cs_list)

    return {
        "ready": f"{ready}/{total}" if total else "0/0",
        "status": _pod_status(status_, cs_list),
        "restarts": restarts,
        # 崩溃原因原文 (UI 展示): CrashLoopBackOff 只说"在重启", 真因在 lastState.terminated
        # (如 "NVML: Driver Not Loaded" = CUDA 镜像落 CPU 节点)。聚合首个非空容器的。
        # pod 级 status.reason (Evicted/NodeLost) 优先: 它是 pod 整体被杀的根因,
        # 比容器各自的退出更能说明问题 (如 Evicted: 节点 ephemeral-storage 不足)。
        "reason": _pod_level_reason(status_) or _pod_failure_reason(cs_list),
        "containers": [_container_summary(c) for c in cs_list],
    }


def _container_summary(c: dict[str, Any]) -> dict[str, Any]:
    """单容器状态 (推理 pod 展开行: 主 sglang + reverse-proxy + otel 各自一行)。"""
    return {
        "name": c.get("name"),
        "ready": bool(c.get("ready")),
        "status": _container_state(c.get("state") or {}),
        "restarts": int(c.get("restart_count") or c.get("restartCount") or 0),
        "reason": _container_reason(c),
    }


def _container_reason(c: dict[str, Any]) -> str | None:
    """单容器崩溃原文: lastState.terminated.message (真因) 优先, 否则 state.waiting.message。

    StartError/OOMKilled 根因在 lastState.terminated (上次退出); 当前 state.waiting
    只有 "back-off restarting" 这类无信息文本, 故 lastState 优先。
    """
    # terminated 可能在 lastState (重启过的容器) 或 state (没重启直接挂的, 如 Evicted
    # 时容器一次性 terminated)。两处都看, lastState 优先 (它是"上次"的更完整记录)。
    last = c.get("last_state") or c.get("lastState") or {}
    term = last.get("terminated") or (c.get("state") or {}).get("terminated") or {}
    if term.get("message"):
        reason = term.get("reason") or ""
        return f"{reason}: {term['message']}" if reason else term["message"]
    # 正常退出 (Completed/Error/OOMKilled) 无 message, 但仍要告诉用户为啥退出 +
    # exitCode (重启>0 时尤其): 否则 UI 看到"重启 1 / 原因 -" 像缺信息。
    if term.get("reason"):
        code = term.get("exit_code")
        if code is None:
            code = term.get("exitCode")
        return f"{term['reason']} (exit {code})" if code is not None else term["reason"]
    waiting = (c.get("state") or {}).get("waiting") or {}
    if waiting.get("message"):
        return waiting["message"]
    return None


def _pod_level_reason(status_: dict[str, Any]) -> str | None:
    """pod 整体被杀的根因: status.reason (Evicted/NodeLost/...) + status.message。

    Evicted 时容器各自的 ContainerStatusUnknown/Error 是结果不是原因; pod 级
    "node low on ephemeral-storage" 才是根因, 故优先。
    """
    reason = status_.get("reason")
    if not reason:
        return None
    msg = status_.get("message")
    return f"{reason}: {msg}" if msg else reason


def _pod_failure_reason(cs_list: list[dict[str, Any]]) -> str | None:
    """容器级崩溃原文: 首个有 reason 的容器 (多容器时主容器一般首个)。"""
    for c in cs_list:
        r = _container_reason(c)
        if r:
            return r
    return None


def _container_state(state: dict[str, Any]) -> str:
    """单容器 STATUS: waiting.reason / terminated.reason / Running。"""
    # k8s to_dict 产出 {"waiting": None, "running": {...}, "terminated": None}:
    # key 在但值 None, state.get("waiting", {}) 拿到 None 不是默认 {}, 故 `or {}`
    if (state.get("waiting") or {}).get("reason"):
        return state["waiting"]["reason"]
    if (state.get("terminated") or {}).get("reason"):
        return state["terminated"]["reason"]
    if state.get("running"):
        return "Running"
    return "Unknown"


def _pod_status(status_: dict[str, Any], cs_list: list[dict[str, Any]]) -> str:
    """kubectl STATUS 列: 容器 waiting/terminated reason 优先, 否则回退 phase。"""
    if status_.get("reason"):  # 如 Evicted / NodeLost
        return status_["reason"]

    for c in cs_list:
        state = c.get("state") or {}
        waiting = state.get("waiting")
        if waiting and waiting.get("reason"):
            return waiting["reason"]  # CrashLoopBackOff / ImagePullBackOff ...
    for c in cs_list:
        state = c.get("state") or {}
        term = state.get("terminated")
        if term and term.get("reason"):
            return term["reason"]  # Completed / Error / OOMKilled ...

    return status_.get("phase") or "Unknown"
