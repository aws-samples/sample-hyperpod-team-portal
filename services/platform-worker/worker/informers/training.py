"""TrainingInformer: watch HyperPodPyTorchJob CR → reconcile phase 到 DDB。

通用 watch 健壮逻辑在 CRInformer 基类 (worker/informers/base.py); 此文件只留训练特有:
坐标 + derive_status_md (用 worker/phase.py) + resolve_ids (训练 label / namespace 反推)。
"""
from __future__ import annotations

from typing import Any

from app.adapters.ddb import tables
from app.adapters.k8s import K8sClient
from app.modules.shared.kueue_status import (
    KUEUE_FINISHED, derive_kueue_status_from_workload, pick_latest_pod,
)
from app.modules.workspace import crud as ws_crud
from worker.informers.base import CRInformer
from worker.phase import derive_phase, derive_train_kueue_status

_LABEL_JOB_ID = "platform.hyperpod.io/training-job-id"
_LABEL_WS_ID = "platform.hyperpod.io/workspace-id"
_LABEL_PRIORITY = "kueue.x-k8s.io/priority-class"


class TrainingInformer(CRInformer):
    group = "sagemaker.amazonaws.com"
    version = "v1"
    plural = "hyperpodpytorchjobs"
    resource_type = tables.RESOURCE_TYPE_TRAIN
    resource_kind = "HyperPodPyTorchJob"

    async def derive_status_md(self, cr: dict[str, Any]) -> dict[str, Any]:
        pr = derive_phase(cr)
        meta = cr.get("metadata") or {}
        labels = meta.get("labels") or {}
        ks = await self._derive_kueue_status(cr, meta, pr)
        # 训练 Failed 但 Pod 还占卡 (cleanPodPolicy=OnlyComplete 下失败 Pod 不清):
        # ks=Finished 时探 Pod, 占卡则标记 → 写入层据此保留 active_ws (留在活跃列表)。
        # occupying_resources 只用于算 active_ws, repo 不落库 (做法1)。
        occupying = await self._is_occupying_resources(cr, meta) if ks == KUEUE_FINISHED else False
        return {
            "phase": pr.phase,
            "started_at": pr.started_at,
            "ended_at": pr.ended_at,
            "last_condition_message": pr.last_condition_message,
            "priority_class": labels.get(_LABEL_PRIORITY),
            # kueue_status = Workload 字段纯镜像 (训练 1 跳: job-uid = CR uid)
            "kueue_status": ks,
            "occupying_resources": occupying,
            # status_detail: 整个 status 原样 (debug 弹窗用)
            "status_detail": cr.get("status") or {},
        }

    async def _is_occupying_resources(self, cr: dict[str, Any], meta: dict[str, Any]) -> bool:
        """探训练 Failed 后是否还长期占卡。仅 ks=Finished 时调。

        关键: 先看 CR 的 spec.runPolicy.cleanPodPolicy (CRD default=All, apiserver 注入,
        几乎不缺失) 决定要不要查 Pod —— 因为 informer 收不到 Pod 删除事件, 不能依赖
        "事后把 occupying 翻 False":
          - cleanPodPolicy=All: 失败 Pod 注定被 operator 自动清 → 不会长期占卡 →
            **直接 False, 不查 Pod** (Failed 瞬间即判, 避免"Pod 删除无事件致 active_ws 残留")。
          - OnlyComplete / None: 失败 Pod 留着长期占卡, 且只能靠删 CR 释放 (走 mark_deleted),
            不会"自己消失" → 查 Pod (phase∈{Running,Pending} → 占卡)。
          - 读不到 (防御): 按 CRD default=All 处理 (不查, 当不占卡)。
        """
        clean_policy = (
            ((cr.get("spec") or {}).get("runPolicy") or {}).get("cleanPodPolicy")
        )
        # All 或读不到 (按 CRD default=All) → Pod 注定被清, 不算长期占卡
        if clean_policy != "OnlyComplete" and clean_policy != "None":
            return False
        # OnlyComplete / None: 失败 Pod 留着 → 查 Pod 判占卡
        ns = meta.get("namespace") or ""
        cr_name = meta.get("name") or ""
        if not (ns and cr_name):
            return False
        try:
            k8s = K8sClient()
            pods = await k8s.list_pods_by_label_selector(ns, f"HPJob={cr_name}")
        except Exception as exc:  # noqa: BLE001 - 查不到不阻塞
            self.log.info("train.occupying.pod_skip err=%s", exc)
            return False
        return any(
            ((p.get("status") or {}).get("phase")) in ("Running", "Pending")
            for p in pods
        )

    async def _derive_kueue_status(self, cr, meta, pr) -> str | None:
        """查 Workload 派生六态 (纯镜像)。查不到时: CR 终态→Finished, 否则 None(保持旧值)。"""
        ns = meta.get("namespace") or ""
        cr_uid = meta.get("uid") or ""
        wl = None
        try:
            k8s = K8sClient()
            wls = await k8s.list_workloads_by_job_uid(ns, cr_uid)
            wl = pick_latest_pod(wls)  # 训练 1:1, 仍取最新防多条
        except Exception as exc:  # noqa: BLE001 - 查不到不阻塞 reconcile
            self.log.info("train.kueue.wl_skip err=%s", exc)
        ks = derive_kueue_status_from_workload(wl)
        if ks is None:
            # 查不到 Workload: CR 终态 → Finished; 非终态(刚建/排队) → None(保持旧值不覆盖)
            if derive_train_kueue_status(cr) == "finished":
                return KUEUE_FINISHED
            return None
        return ks

    async def resolve_ids(self, cr: dict[str, Any]) -> tuple[str, str] | None:
        meta = cr.get("metadata") or {}
        labels = meta.get("labels") or {}
        job_id = labels.get(_LABEL_JOB_ID)
        ws_id = labels.get(_LABEL_WS_ID)
        if job_id and ws_id:
            return job_id, ws_id
        # 绕过 UI: namespace 反推 ws
        ns = meta.get("namespace") or ""
        ws = await ws_crud.get_workspace_by_namespace(None, None, ns)
        if ws is None:
            return None
        resolved_ws = str(ws.get("workspace_id") or ws.get("id"))
        resolved_job = job_id or meta.get("uid") or meta.get("name")
        if not resolved_job:
            return None
        return resolved_job, resolved_ws


async def run_training_informer(hb: Any) -> None:
    """供 main.py 调 (签名保持不变, main 不用改)。"""
    await TrainingInformer(context=None).run(hb)
