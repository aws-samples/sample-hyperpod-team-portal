"""优先级管理编排: WPC 档位 + 单任务优先级 + 抢占开关.


档位增删改列走 SageMaker scheduler_config (task governance 权威源), 无 DDB。
单任务优先级改动 (patch_task_priority) + 抢占开关 (get/set_preemption) 仍走 K8s。

权限: WPC 增删改 + 抢占开关 = 仅平台超管; 改单任务 = ws 成员。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import scheduler_config
from app.adapters.aws.scheduler_config import SchedulerConfigError
from app.core.config import get_settings
from app.core.i18n import t
from app.modules.workspace.persistence import crud as ws_crud
from app.services.k8s_client import K8sClient

_DEFAULT_NS = "default"


def _http_from_scheduler_error(exc: SchedulerConfigError) -> HTTPException:
    """SchedulerConfigError → HTTPException 映射 (按设计文档错误表).

    - 集群/policy 未配置 → 400 (可操作: 去建 cluster policy)
    - 同名冲突 / 版本过期 → 409
    - 其余 API 错误 (describe/update failed 等) → 502
    """
    msg = str(exc)
    lower = msg.lower()
    if "empty" in lower or "no cluster policy" in lower:
        return HTTPException(status.HTTP_400_BAD_REQUEST, msg)
    if "not managed by sagemaker" in lower or "conflict" in lower or "targetversion" in lower:
        return HTTPException(status.HTTP_409_CONFLICT, msg)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, msg)


def _cluster_queue_name(namespace: str) -> str:
    """ws ClusterQueue 命名约定: <namespace>-clusterqueue (实测)。"""
    return f"{namespace}-clusterqueue"


async def _ws_namespace(ws_id: str) -> str:
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    return ws.get("namespace") or _DEFAULT_NS


# ---------- WorkloadPriorityClass 档位 ----------

async def list_priority_classes(k8s: K8sClient) -> list[dict[str, Any]]:
    """列所有档 (走 SageMaker scheduler config; k8s 参数保留兼容签名, 不用)."""
    name = get_settings().hyperpod_cluster_name
    try:
        rows = await scheduler_config.list_priority_classes(name)
    except SchedulerConfigError as exc:
        raise _http_from_scheduler_error(exc) from exc
    return [
        {
            "name": r["name"],
            "value": r["value"],
            "description": r.get("description"),
            "in_use_count": 0,
        }
        for r in rows
    ]


async def create_priority_class(
    k8s: K8sClient, name: str, value: int, description: str | None
) -> dict[str, Any]:
    """建档: 前端传的 name 可能带 -priority (兼容), service 剥成裸名调 SageMaker."""
    bare = scheduler_config.to_bare_name(name)
    hp_name = get_settings().hyperpod_cluster_name
    try:
        await scheduler_config.upsert_priority_class(hp_name, bare_name=bare, weight=value)
    except SchedulerConfigError as exc:
        raise _http_from_scheduler_error(exc) from exc
    return {
        "name": scheduler_config.to_wpc_name(bare),
        "value": value,
        "description": None,  # 官方 API 无 description 入参; 忽略前端传入的 description
        "in_use_count": 0,
    }


async def update_priority_class(
    k8s: K8sClient, name: str, value: int | None, description: str | None
) -> dict[str, Any]:
    """改档: 仅 weight 可改 (description 官方 API 不支持); value=None 视为 no-op 返回当前值."""
    if value is None:
        rows = await list_priority_classes(k8s)
        found = next((r for r in rows if r["name"] == name), None)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, t("priority.class_not_found", name=name))
        return found
    bare = scheduler_config.to_bare_name(name)
    hp_name = get_settings().hyperpod_cluster_name
    try:
        await scheduler_config.upsert_priority_class(hp_name, bare_name=bare, weight=value)
    except SchedulerConfigError as exc:
        raise _http_from_scheduler_error(exc) from exc
    return {
        "name": scheduler_config.to_wpc_name(bare),
        "value": value,
        "description": None,
        "in_use_count": 0,
    }


async def delete_priority_class(k8s: K8sClient, name: str) -> None:
    """删档: name 可能是全名 (list 返的), service 剥成裸名."""
    bare = scheduler_config.to_bare_name(name)
    hp_name = get_settings().hyperpod_cluster_name
    try:
        await scheduler_config.delete_priority_class(hp_name, bare_name=bare)
    except SchedulerConfigError as exc:
        raise _http_from_scheduler_error(exc) from exc


# ---------- 单任务优先级 ----------

async def list_workloads(k8s: K8sClient, ws_id: str) -> list[dict[str, Any]]:
    namespace = await _ws_namespace(ws_id)
    out = []
    for wl in await k8s.list_workloads(namespace):
        meta = wl.get("metadata") or {}
        spec = wl.get("spec") or {}
        owners = meta.get("ownerReferences") or []
        conds = (wl.get("status") or {}).get("conditions") or []
        admitted = any(
            c.get("type") == "Admitted" and c.get("status") == "True" for c in conds
        )
        out.append(
            {
                "workload_name": meta.get("name"),
                "owner_name": owners[0].get("name") if owners else None,
                "owner_kind": owners[0].get("kind") if owners else None,
                "priority": spec.get("priority"),
                "priority_class_name": spec.get("priorityClassName"),
                "admitted": admitted,
                "queue_name": spec.get("queueName"),
            }
        )
    return out


async def patch_task_priority(
    k8s: K8sClient,
    ws_id: str,
    task_type: str,
    cr_name: str,
    priority_class_name: str,
) -> dict[str, Any]:
    """按 (task_type, CR name) 反查 Workload, 改源 CR label + 删 Workload 让 Kueue 重建。

    task_type 由前端 TaskRow.kind 传 (dev/train/inference)。三类 Workload 关联链不同
    (训练 owned by CR, 开发机/推理 owned by Pod), 用 find_workload_for_task 按 type
    走 uid-based 精确查找 (替代只对训练成立的 owner.name 匹配)。
    pending 任务立即重排; running 影响抢占。
    """
    # 多机推理 (dynamo) 暂不支持改优先级: 其优先级传播链 (DGD priority-class label →
    # Grove PodCliqueSet → Pod → Workload) 目前未打通, Workload.priority 恒 0; 且一任务
    # 多 Workload 的统一改法/重建触发点未定 (待与 dynamo 集成对齐)。前端已对 dynamo 隐藏
    # 改优先级入口, 此处再兜底: 返回友好 400 而非之前 _job_uid_for_task 抛的 500。
    if task_type == "dynamo":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t("priority.dynamo_unsupported"),
        )
    namespace = await _ws_namespace(ws_id)
    wl = await k8s.find_workload_for_task(namespace, task_type, cr_name)
    if wl is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            t("priority.workload_not_found", cr_name=cr_name),
        )
    # 校验目标档存在 (走 SageMaker scheduler config, 与档管理同源)
    rows = await list_priority_classes(k8s)
    target = next((r for r in rows if r["name"] == priority_class_name), None)
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, t("priority.target_class_not_found", name=priority_class_name)
        )
    value = int(target.get("value") or 0)
    wl_name = (wl.get("metadata") or {}).get("name")
    # 已完成任务禁止改 (无意义)
    conds = (wl.get("status") or {}).get("conditions") or []
    if any(c.get("type") == "Finished" and c.get("status") == "True" for c in conds):
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("priority.task_finished")
        )
    # 实测 (2026-06-11): Workload.spec.priority 被 Kueue webhook 锁死, 直接 patch 不生效。
    # 正确做法 = 改源 priority-class label + 让 Kueue 按新 label 重建 Workload。但三类
    # "重建" 的触发点不同 (Workload 的 priority 来源不同):
    #   训练/rayjob: Workload owned by CR → 改 CR label + 删 Workload, Kueue 按 CR 新 label 重建。
    #     (RayJob 的 Workload ownerRef 直指 RayJob CR, 与训练同构, 走删 Workload 而非删 Deployment。)
    #   开发机/推理: Workload owned by Pod, Pod 的 label 来自 Deployment template (operator
    #     按 CR 创建时 label 写入)。改 CR label 不会同步到已存 Deployment → 必须删 Deployment,
    #     operator 按 CR 当前 label 重建 Deployment → 新 Pod → Kueue 按新 label 建 Workload。
    #     ⚠️ 删 Deployment = 重启用户的开发机/推理容器 (会话中断)。
    await k8s.patch_task_priority_label(task_type, namespace, cr_name, priority_class_name)
    if task_type in ("train", "rayjob"):
        await k8s.delete_workload(namespace, wl_name)
        note = t("priority.note_workload", name=wl_name)
    else:
        # 开发机 Deployment = workspace-{cr_name}; 推理 Deployment = {cr_name}
        dep_name = f"workspace-{cr_name}" if task_type == "dev" else cr_name
        await k8s.delete_deployment(namespace, dep_name)
        note = t("priority.note_deployment", name=dep_name)
    return {
        "workload_name": wl_name,
        "owner_name": cr_name,
        "priority": value,
        "priority_class_name": priority_class_name,
        "note": note,
    }


# ---------- 抢占开关 ----------

async def get_preemption(k8s: K8sClient, ws_id: str) -> dict[str, Any]:
    namespace = await _ws_namespace(ws_id)
    cq_name = _cluster_queue_name(namespace)
    cq = await k8s.get_clusterqueue(cq_name)
    within = (
        ((cq.get("spec") or {}).get("preemption") or {}).get("withinClusterQueue")
        or "Never"
    )
    return {
        "workspace_id": ws_id,
        "namespace": namespace,
        "cluster_queue": cq_name,
        "within_cluster_queue": within,
    }


async def set_preemption(
    k8s: K8sClient, ws_id: str, within_cluster_queue: str
) -> dict[str, Any]:
    namespace = await _ws_namespace(ws_id)
    cq_name = _cluster_queue_name(namespace)
    await k8s.patch_clusterqueue_preemption(cq_name, within_cluster_queue)
    return {
        "workspace_id": ws_id,
        "namespace": namespace,
        "cluster_queue": cq_name,
        "within_cluster_queue": within_cluster_queue,
    }
