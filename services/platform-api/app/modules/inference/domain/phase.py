"""InferenceEndpointConfig CR status → phase 归一化 (纯函数)。

(历史: 曾用于把 CR status 归一成 Pending / Provisioning / Running / Failed;
现 phase 全链路走 CR 原始值, 不再归一 — 见 derive_inference_phase 的废弃标注。)
"""
from __future__ import annotations

from typing import Any


def runtime_url_from_arn(arn: str | None) -> str | None:
    """SageMaker endpoint ARN → runtime invoke URL (纯函数, informer 和 sync 共用)。

    operator 不填 status.endpointUrl, 只在 status.endpoints.sagemaker.endpointArn
    给 ARN。调用地址是 SageMaker runtime 固定格式:
        https://runtime.sagemaker.<region>.amazonaws.com/endpoints/<name>/invocations
    ARN: arn:aws:sagemaker:<region>:<acct>:endpoint/<name>
    """
    if not arn:
        return None
    parts = arn.split(":")
    if len(parts) < 6 or "/" not in parts[5]:
        return None
    region = parts[3]
    name = parts[5].split("/", 1)[1]
    if not region or not name:
        return None
    return (
        f"https://runtime.sagemaker.{region}.amazonaws.com"
        f"/endpoints/{name}/invocations"
    )


def derive_inference_phase(cr: dict[str, Any]) -> str:
    """⚠️ 已废弃 (不再用于 DDB phase): phase 现全链路存 CR 原始
    deploymentObjectOverallState/state, 不再归一。本函数仅保留作纯函数 +
    test_phase.py 守护, 勿在 sync/informer 重新引用 (会回归两套词表冲突)。
    """
    status_ = cr.get("status") or {}
    conditions = status_.get("conditions") or []
    by_type = {c.get("type"): c for c in conditions}

    # operator 实际 schema: status.deploymentStatus.{deploymentObjectOverallState, status.conditions}
    deploy_status = status_.get("deploymentStatus") or {}
    deploy_overall = deploy_status.get("deploymentObjectOverallState") or ""
    deploy_inner = deploy_status.get("status") or {}
    deploy_conds = deploy_inner.get("conditions") or []
    deploy_by_type = {c.get("type"): c for c in deploy_conds}
    deploy_available = (deploy_by_type.get("Available") or {}).get("status") == "True"
    deploy_ready_replicas = int(deploy_inner.get("readyReplicas") or 0)
    state_top = (status_.get("state") or "").lower()

    def _true(t: str) -> bool:
        return (by_type.get(t) or {}).get("status") == "True"

    if _true("DeploymentFailed") or _true("Failed") or "fail" in state_top:
        return "Failed"
    if (
        _true("Available")
        or _true("Running")
        or (
            deploy_overall == "DeploymentComplete"
            and deploy_available
            and deploy_ready_replicas > 0
        )
    ):
        return "Running"
    if (
        _true("Provisioning")
        or _true("InProgress")
        or _true("Pending")
        or "progress" in state_top
        or deploy_overall in {"DeploymentInProgress", "DeploymentPending"}
    ):
        return "Provisioning"
    return status_.get("phase") or "Pending"


_INF_FINISHED = {
    "DeploymentFailed", "DeletionPending", "DeletionInProgress",
    "DeletionFailed", "DeletionComplete", "Stopped", "Deleted",
}


# 注: 旧 derive_inf_kueue_status / _pod_is_gated 已删 (kueue_status 改为镜像 Workload,
# 由 worker InferenceInformer 查 Workload 派生六态; _INF_FINISHED 仍用于 None 分支判终态)。
