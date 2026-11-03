"""llm-d LWS → 详情页实时快照 (分支B).

照 dynamo sync: 详情页 sync=true 时【实时拉】LWS status + pods 给前端展示,
不回写 DDB 状态字段 (phase/kueue_status 归 Go platform-controller, 避免抢写)。

pod 定位: 一组资源 (gateway/leader/worker) 都打 app.kubernetes.io/instance=<name>,
故按该 label 一把捞全 (role 由 pod 自身 label 区分, builder 汇总)。
LWS 名 = <name>-multi (cr.py 约定)。
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.llmd.persistence import crud
from app.modules.shared.kueue_status import is_terminal
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

# 一组资源共享的实例 label (cr.py 给 gateway/leader/worker 都打)
_POD_LABEL_KEY = "app.kubernetes.io/instance"
# 单个 pod 的角色 label; gateway pod 的值 = <name>-gateway (cr.py 约定)
_POD_NAME_LABEL = "app.kubernetes.io/name"


def _gateway_has_ready_pod(pods: list[dict[str, Any]], base_name: str) -> bool:
    """gateway 是否至少有一个 pod Ready (等价 Deployment.readyReplicas, 省一次查询)。

    依赖 readinessProbe 打 /readiness: 换回 /health 则 Ready 不再代表背后有可用 worker。
    """
    gw = f"{base_name}-gateway"
    for p in pods:
        if ((p.get("metadata") or {}).get("labels") or {}).get(_POD_NAME_LABEL) != gw:
            continue
        for c in (p.get("status") or {}).get("conditions") or []:
            if c.get("type") == "Ready" and c.get("status") == "True":
                return True
    return False


async def sync_from_k8s(
    db: Any, k8s: K8sClient, row: dict[str, Any]
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """读 LWS .status.conditions + pods + 关联 Workloads 给详情页实时展示。

    返回 (row, conditions, pods, workloads)。row 状态字段不改 (归 Go controller),
    仅 LWS 消失时兜底 mark_stopped (非终态)。
    """
    del db
    base_name = row["name"]
    lws_name = f"{base_name}-multi"
    try:
        lws = await k8s.get_leaderworkerset(row["k8s_namespace"], lws_name)
    except K8sAPIError as exc:
        if "404" in exc.code:
            if is_terminal(row.get("kueue_status")):
                return row, [], [], []
            row = await crud.mark_stopped(None, row)
            return row, [], [], []
        logger.info(
            "llmd.sync.k8s_err",
            id=str(row.get("id")),
            code=exc.code,
            msg=exc.message,
        )
        return row, [], [], []

    status_ = lws.get("status") or {}
    conditions = status_.get("conditions") or []

    try:
        pods = await k8s.list_pods_by_label_selector(
            row["k8s_namespace"],
            f"{_POD_LABEL_KEY}={base_name}",
        )
    except K8sAPIError:
        pods = []

    try:
        all_wls = await k8s.list_workloads(row["k8s_namespace"])
    except K8sAPIError:
        all_wls = []
    pod_names = {
        n for p in pods if (n := (p.get("metadata") or {}).get("name"))
    }
    workloads = [
        wl
        for wl in all_wls
        if any(
            ref.get("kind") == "Pod" and ref.get("name") in pod_names
            for ref in (wl.get("metadata") or {}).get("ownerReferences") or []
        )
    ]

    # alb_dns 一有 hostname 就填; endpoint_url 还要等 gateway Ready ——
    # ALB 地址比 pod 就绪早得多 (75s vs 冷启动几分钟), 早给会 503。
    try:
        alb_dns = await k8s.get_alb_dns(row["k8s_namespace"], base_name)
    except K8sAPIError:
        alb_dns = None
    row["alb_dns"] = alb_dns
    row["endpoint_url"] = (
        f"http://{alb_dns}"
        if alb_dns and _gateway_has_ready_pod(pods, base_name)
        else None
    )

    return row, conditions, pods, workloads
