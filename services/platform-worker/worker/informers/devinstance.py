"""DevInstanceInformer: watch Workspace CR → reconcile 状态到 DDB。

通用 watch 逻辑在 CRInformer 基类; 此文件只留开发机特有:
坐标 + derive_status_md (用 devinstance.domain.phase) + resolve_ids。
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
from worker.phase import pick_single_phase

_LABEL_DEV_ID = "platform.hyperpod.io/dev-instance-id"
_LABEL_WS_ID = "platform.hyperpod.io/workspace-id"
_LABEL_PRIORITY = "kueue.x-k8s.io/priority-class"


class DevInstanceInformer(CRInformer):
    group = "workspace.jupyter.org"
    version = "v1alpha1"
    plural = "workspaces"
    resource_type = tables.RESOURCE_TYPE_DEV
    resource_kind = "Workspace"

    async def derive_status_md(self, cr: dict[str, Any]) -> dict[str, Any]:
        status_ = cr.get("status") or {}
        cond_list = status_.get("conditions") or []
        conds = {c.get("type"): c for c in cond_list}

        # 原始 phase: 取单个状态 (先 lastTransitionTime 最新, 时间戳相同按固定优先级)
        true_conds = [c for c in cond_list if c.get("status") == "True"]
        phase = pick_single_phase(cond_list)

        # started_at: Available condition 的 lastTransitionTime
        started_at = (conds.get("Available") or {}).get("lastTransitionTime")
        # ended_at: Stopped condition 的 lastTransitionTime
        ended_at = (conds.get("Stopped") or {}).get("lastTransitionTime")

        latest = cond_list[-1] if cond_list else {}
        labels = (cr.get("metadata") or {}).get("labels") or {}

        # kueue_status = Workload 字段纯镜像 (开发机 2 跳: 最新 Pod uid → Workload)
        kueue_status = await self._derive_kueue_status(cr, phase)

        return {
            "phase": phase,
            "started_at": started_at,
            "ended_at": ended_at,
            "last_condition_message": latest.get("message"),
            "priority_class": labels.get(_LABEL_PRIORITY),
            "kueue_status": kueue_status,
            # status_detail: 所有 status==True 的 condition 数组 (无则 [])
            "status_detail": true_conds,
        }

    async def _derive_kueue_status(self, cr: dict[str, Any], phase: str) -> str | None:
        """派生六态。CR 终态优先于 Workload (停止开发机的竞态修复)。

        - CR 终态 (phase 含 Stopped/Degraded) → 直接 Finished, **不查 Workload**。
          否则停止瞬间 Workload 还没被级联删, 会查到残留 Admitted → 误判为活跃。
          (开发机停止=patch desiredStatus=Stopped, CR 保留; 重启 patch 回 Running 时
          phase 不再含 Stopped → 走下面查 Workload 正常恢复活跃。)
        - CR 非终态: 查 Workload 镜像六态; 查不到 → None (保持 DDB 旧值不覆盖)。
        """
        p = phase or ""
        if "Stopped" in p or "Degraded" in p:
            return KUEUE_FINISHED
        meta = cr.get("metadata") or {}
        ns = meta.get("namespace") or ""
        name = meta.get("name") or ""
        ks = None
        try:
            k8s = K8sClient()
            pods = await k8s.list_pods_by_workspace(ns, name)
            pod = pick_latest_pod(pods)
            if pod is not None:
                pod_uid = (pod.get("metadata") or {}).get("uid") or ""
                wls = await k8s.list_workloads_by_job_uid(ns, pod_uid)
                ks = derive_kueue_status_from_workload(pick_latest_pod(wls))
        except Exception as exc:  # noqa: BLE001 - 查不到不阻塞 reconcile
            self.log.info("dev.kueue.wl_skip err=%s", exc)
        return ks

    async def resolve_ids(self, cr: dict[str, Any]) -> tuple[str, str] | None:
        meta = cr.get("metadata") or {}
        labels = meta.get("labels") or {}
        dev_id = labels.get(_LABEL_DEV_ID)
        ws_id = labels.get(_LABEL_WS_ID)
        if dev_id and ws_id:
            return dev_id, ws_id
        # 绕过 UI: namespace 反推 ws
        ns = meta.get("namespace") or ""
        ws = await ws_crud.get_workspace_by_namespace(None, None, ns)
        if ws is None:
            return None
        resolved_ws = str(ws.get("workspace_id") or ws.get("id"))
        resolved_id = dev_id or meta.get("uid") or meta.get("name")
        if not resolved_id:
            return None
        return resolved_id, resolved_ws


async def run_devinstance_informer(hb: Any) -> None:
    """供 main.py 调。"""
    await DevInstanceInformer(context=None).run(hb)
