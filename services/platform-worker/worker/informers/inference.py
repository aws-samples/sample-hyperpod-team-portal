"""InferenceInformer: watch InferenceEndpointConfig CR → reconcile 状态到 DDB。

通用 watch 逻辑在 CRInformer 基类; 此文件只留推理特有:
坐标 + derive_status_md (用 inference.domain.phase) + resolve_ids。
"""
from __future__ import annotations

from typing import Any

from app.adapters.ddb import tables
from app.adapters.k8s import K8sClient
from app.modules.inference.domain.phase import _INF_FINISHED, runtime_url_from_arn
from app.modules.shared.kueue_status import (
    KUEUE_FINISHED, derive_kueue_status_from_workload, pick_latest_pod,
)
from app.modules.workspace import crud as ws_crud
from worker.informers.base import CRInformer

_LABEL_INF_ID = "platform.hyperpod.io/inference-id"
_LABEL_WS_ID = "platform.hyperpod.io/workspace-id"
_LABEL_PRIORITY = "kueue.x-k8s.io/priority-class"


class InferenceInformer(CRInformer):
    group = "inference.sagemaker.aws.amazon.com"
    version = "v1"
    plural = "inferenceendpointconfigs"
    resource_type = tables.RESOURCE_TYPE_INFERENCE
    resource_kind = "InferenceEndpointConfig"

    async def derive_status_md(self, cr: dict[str, Any]) -> dict[str, Any]:
        status_ = cr.get("status") or {}
        conditions = status_.get("conditions") or []
        latest = conditions[-1] if conditions else {}
        labels = (cr.get("metadata") or {}).get("labels") or {}
        deploy_status = status_.get("deploymentStatus") or {}
        # 原始 phase: deploymentObjectOverallState; 缺失 → 回退 status.state
        phase = (
            deploy_status.get("deploymentObjectOverallState")
            or status_.get("state")
            or ""
        )
        # operator 不填 status.endpointUrl, 只给 endpoints.sagemaker.endpointArn;
        # 调用地址从 ARN 拼 SageMaker runtime URL (见 runtime_url_from_arn)。
        sm_arn = (
            (status_.get("endpoints") or {}).get("sagemaker") or {}
        ).get("endpointArn")

        # kueue_status = Workload 字段纯镜像 (推理 2 跳: 最新 Pod uid → Workload)
        kueue_status = await self._derive_kueue_status(cr, phase)

        return {
            "phase": phase,
            "endpoint_url": (
                status_.get("endpointUrl")
                or status_.get("invocationUrl")
                or runtime_url_from_arn(sm_arn)
            ),
            "last_condition_message": latest.get("message"),
            "priority_class": labels.get(_LABEL_PRIORITY),
            "kueue_status": kueue_status,
            # status_detail: {state, conditions, deploymentStatus} 三段
            "status_detail": {
                "state": status_.get("state"),
                "conditions": conditions,
                "deploymentStatus": deploy_status,
            },
        }

    async def _derive_kueue_status(self, cr: dict[str, Any], phase: str) -> str | None:
        """查 Workload 派生六态 (纯镜像, 2 跳: 最新 Pod uid → Workload)。

        查不到时: CR 终态(_INF_FINISHED, 不含运行态 DeploymentComplete) → Finished;
        否则 None(保持DDB旧值不覆盖)。
        """
        meta = cr.get("metadata") or {}
        ns = meta.get("namespace") or ""
        name = meta.get("name") or ""
        ks = None
        try:
            k8s = K8sClient()
            pods = await k8s.list_pods_by_label_selector(ns, f"app={name}")
            pod = pick_latest_pod(pods)
            if pod is not None:
                pod_uid = (pod.get("metadata") or {}).get("uid") or ""
                wls = await k8s.list_workloads_by_job_uid(ns, pod_uid)
                ks = derive_kueue_status_from_workload(pick_latest_pod(wls))
        except Exception as exc:  # noqa: BLE001 - 查不到不阻塞 reconcile
            self.log.info("inf.kueue.wl_skip err=%s", exc)
        if ks is None and (phase or "") in _INF_FINISHED:
            return KUEUE_FINISHED
        return ks

    async def resolve_ids(self, cr: dict[str, Any]) -> tuple[str, str] | None:
        meta = cr.get("metadata") or {}
        labels = meta.get("labels") or {}
        inf_id = labels.get(_LABEL_INF_ID)
        ws_id = labels.get(_LABEL_WS_ID)
        if inf_id and ws_id:
            return inf_id, ws_id
        # 绕过 UI: namespace 反推 ws
        ns = meta.get("namespace") or ""
        ws = await ws_crud.get_workspace_by_namespace(None, None, ns)
        if ws is None:
            return None
        resolved_ws = str(ws.get("workspace_id") or ws.get("id"))
        resolved_id = inf_id or meta.get("uid") or meta.get("name")
        if not resolved_id:
            return None
        return resolved_id, resolved_ws


async def run_inference_informer(hb: Any) -> None:
    """供 main.py 调。"""
    await InferenceInformer(context=None).run(hb)
