"""InferenceEndpointConfig CR → DDB phase 同步 (DDB-only —).

Operator status conditions (实测):
    - InProgress / Pending / Provisioning (拉模型 + 起 pod)
    - Available / Running (endpoint ready)
    - Failed
    - status.endpointUrl: ALB DNS, ready 才填

Phase (CR 原始值, 不再归一):
    写 deploymentStatus.deploymentObjectOverallState (缺失回退顶层 status.state)。
    前端按原始值直接展示, 不翻译成统一词表。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.inference.domain.phase import runtime_url_from_arn
from app.modules.inference.persistence import crud
from app.modules.shared.kueue_status import is_terminal
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

# sync 只落库它独占的字段: endpoint_url (即时刷新) + alb_dns (informer 不写)。
# 仅这俩变才写 DDB。phase/status_detail/last_condition_message 归 informer, 不参与 dirty。
_DIRTY_KEYS = ("endpoint_url", "alb_dns")


def _collect_conditions(
    status_: dict[str, Any], alb_dns: str | None = None
) -> list[dict[str, Any]]:
    """固定 4 阶段骨架 (需求3 · A 方案): 每阶段去 IEC status 找对应信号,
    命中且达成 → status=True (前端绿); 缺失/未达成 → status=Unknown (前端灰)。

    阶段全集 (实测来源 aaa-37ca18):
      1 Progressing       deploymentStatus.status.conditions[Progressing]
      2 Available         deploymentStatus.status.conditions[Available]
      3 LoadBalancer      internal ALB Ingress 是否分到地址 (alb_dns 非空)
      4 SageMakerEndpoint  endpoints.sagemaker.state (== *Completed*)

    阶段 3 用 ALB 就绪替代原 DeploymentComplete (后者与 Available 语义重叠, 信息量低)。
    固定顺序输出, 不按时间排 (骨架式: 用户一眼看进度到哪个阶段)。
    """
    deploy_inner = (status_.get("deploymentStatus") or {}).get("status") or {}
    deploy_by_type = {
        c.get("type"): c for c in (deploy_inner.get("conditions") or [])
    }
    sm = (status_.get("endpoints") or {}).get("sagemaker") or {}
    sm_state = sm.get("state")

    def _stage(
        type_: str,
        src: dict[str, Any] | None,
        *,
        default_msg: str,
    ) -> dict[str, Any]:
        # src 有 → 用真值 (status/reason/message/lastTransitionTime); 缺 → Unknown 占位灰
        if src:
            return {
                "type": type_,
                "status": src.get("status") or "Unknown",
                "reason": src.get("reason"),
                "message": src.get("message") or default_msg,
                "lastTransitionTime": src.get("lastTransitionTime"),
            }
        return {
            "type": type_,
            "status": "Unknown",
            "reason": None,
            "message": default_msg,
            "lastTransitionTime": None,
        }

    # ALB 就绪: internal ALB Ingress 分到 hostname (alb_dns 非空) 即可调
    alb_stage = {
        "type": "LoadBalancer",
        "status": "True" if alb_dns else "Unknown",
        "reason": "Provisioned" if alb_dns else None,
        # 就绪文案会经 last_condition_message 落库 (取最后一个已达成阶段), 不能随请求语言变 →
        # 直接英文; 仅未就绪的占位文案 (不落库) 走 t()。
        "message": (
            f"Internal ALB ready: {alb_dns}"
            if alb_dns
            else t("inference.stage_waiting_alb")
        ),
        # ALB hostname 无真实 transition 时间, 不给 lastTransitionTime (避免误导)
        "lastTransitionTime": None,
    }

    sm_stage = (
        {
            "type": "SageMakerEndpoint",
            # SageMaker endpoint 无真实 transition 时间, 不给 lastTransitionTime (避免误导)
            "status": "True" if sm_state and "Completed" in sm_state else "Unknown",
            "reason": sm_state,
            "message": (
                f"SageMaker endpoint state: {sm_state}"
                if sm_state
                else t("inference.stage_sagemaker_not_created")
            ),
            "lastTransitionTime": None,
        }
    )

    return [
        _stage("Progressing", deploy_by_type.get("Progressing"),
               default_msg=t("inference.stage_waiting_replicaset")),
        _stage("Available", deploy_by_type.get("Available"),
               default_msg=t("inference.stage_waiting_min_available")),
        alb_stage,
        sm_stage,
    ]


async def sync_from_k8s(
    db: Any, k8s: K8sClient, row: dict[str, Any]
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """读 IEC CR .status + pods, 回写 DDB metadata.phase + endpoint_url.

    优化: dirty check, 关键字段没变就不写 DDB.
    """
    del db
    snapshot = {k: row.get(k) for k in _DIRTY_KEYS}
    try:
        cr = await k8s.get_inference_endpoint(
            row["k8s_namespace"], row["k8s_endpoint_name"]
        )
    except K8sAPIError as exc:
        if "404" in exc.code:
            # CR 没了: 据 kueue_status 区分 —
            #   终态 = 已被正常终态路径处理 (用户 stop/delete / informer 收 DELETED,
            #          mark_stopped/mark_deleted 都写了 Finished) → 不做任何事。
            #   非终态 = 外部 kubectl 绕过平台删 CR (没人走终态流程) →
            #          mark_stopped 标终态 + 保留行供查日志。
            if is_terminal(row.get("kueue_status")):
                return row, [], [], []
            row = await crud.mark_stopped(None, row)
            return row, [], [], []
        logger.info(
            "inference.sync.k8s_err",
            id=str(row.get("id")),
            code=exc.code,
            msg=exc.message,
        )
        return row, [], [], []

    status_ = cr.get("status") or {}

    # alb_dns 提前取 (状态时间线 LoadBalancer 阶段要用); 失败回退 row 旧值
    try:
        row["alb_dns"] = await k8s.get_alb_dns(
            row["k8s_namespace"], row["k8s_endpoint_name"]
        )
    except (K8sAPIError, AttributeError):
        pass

    conditions = _collect_conditions(status_, row.get("alb_dns"))

    # phase 原始值: deploymentObjectOverallState 缺失回退 status.state (与 informer 同源)。
    # 不再归一 (去 derive_inference_phase) — 失败态 DeploymentFailed 本就在原始值里。
    deploy_ = status_.get("deploymentStatus") or {}
    row["phase"] = (
        deploy_.get("deploymentObjectOverallState")
        or status_.get("state")
        or ""
    )

    # endpoint URL: operator 实际不填 status.endpointUrl, 而是把 SageMaker endpoint
    # ARN 放在 status.endpoints.sagemaker.endpointArn (endpoint InService 后)。
    # 调用地址是 SageMaker runtime 标准格式, 从 ARN 的 region+name 拼出。
    # 兼容老字段 (endpointUrl/invocationUrl) 优先, 都没有则从 ARN 拼。
    sm_arn = (
        (status_.get("endpoints") or {}).get("sagemaker") or {}
    ).get("endpointArn")
    row["endpoint_url"] = (
        status_.get("endpointUrl")
        or status_.get("invocationUrl")
        or runtime_url_from_arn(sm_arn)
        or row.get("endpoint_url")
    )

    # last_condition_message: 取最后一个已达成 (status=True) 阶段的 message;
    # 骨架里 Unknown 占位条不算 (否则永远显示"尚未创建 SageMaker endpoint")。
    achieved = [c for c in conditions if c.get("status") == "True"]
    latest = achieved[-1] if achieved else {}
    row["last_condition_message"] = latest.get("message")

    # status_detail: 与 informer (worker/informers/inference.py) 同构 — 三段。
    # 注: conditions 用 IEC CR 原始 status.conditions (非 _collect_conditions 的骨架),
    # 保持与 informer 写入一致 (debug 弹窗看原始)。
    row["status_detail"] = {
        "state": status_.get("state"),
        "conditions": status_.get("conditions") or [],
        "deploymentStatus": status_.get("deploymentStatus") or {},
    }
    row["last_sync_at"] = datetime.now(UTC).isoformat()

    # 列 pods (用 app=<endpoint_name> 反查 operator 起的 pod)
    # 注: Operator 给 Pod 实际打的是 ``app=<k8s_endpoint_name>``,
    # 不是 ``sagemaker.amazonaws.com/endpoint-name=...``.
    try:
        pods = await k8s.list_pods_by_label_selector(
            row["k8s_namespace"],
            f"app={row['k8s_endpoint_name']}",
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

    dirty = any(row.get(k) != snapshot[k] for k in _DIRTY_KEYS)
    if dirty:
        await crud.update(None, row)
    return row, conditions, pods, workloads
