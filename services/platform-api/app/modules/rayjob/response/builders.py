"""RayJob 响应视图构建."""

from __future__ import annotations

from typing import Any

from app.core.pod_status import summarize_pod
from app.modules.rayjob.api.schemas import (
    ExtraFsxMount,
    RayEnvSecret,
    RayJobDetail,
    RayJobListItem,
    S3DatasetMount,
)
from app.modules.workspace import crud as ws_crud


def _pod_summary(p: dict[str, Any]) -> dict[str, Any]:
    meta = p.get("metadata") or {}
    status_ = p.get("status") or {}
    agg = summarize_pod(p)
    lbls = meta.get("labels") or {}
    return {
        "name": meta.get("name"),
        # KubeRay pod 角色: head / worker (ray.io/node-type)
        "role": lbls.get("ray.io/node-type"),
        "phase": status_.get("phase"),
        "ready": agg["ready"],
        "status": agg["status"],
        "restarts": agg["restarts"],
        "reason": agg["reason"],
        "containers": agg["containers"],
        "node_name": (p.get("spec") or {}).get("node_name"),
        "pod_ip": status_.get("pod_ip"),
        "host_ip": status_.get("host_ip"),
        "start_time": status_.get("start_time"),
    }


async def build_list_item(db: Any, row: dict[str, Any]) -> RayJobListItem:
    del db
    phase = "Stopped" if row.get("stop_requested") else (row.get("phase") or "initializing")
    return RayJobListItem(
        id=str(row.get("id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        creator_user_id=str(row.get("creator_user_id") or ""),
        creator_display_name=row.get("creator_display_name")
        or row.get("creator_user_id")
        or "",
        name=row.get("name") or "",
        display_name=row.get("display_name") or "",
        phase=phase,
        kueue_status=row.get("kueue_status"),
        worker_replicas=int(row.get("worker_replicas") or 1),
        worker_instance_type=row.get("worker_instance_type") or "",
        gpu_per_node=int(row.get("gpu_per_node") or 1),
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        created_at=row.get("created_at") or "",
        last_sync_at=row.get("last_sync_at"),
    )


async def build_detail(
    db: Any,
    row: dict[str, Any],
    conditions: list[dict[str, Any]] | None = None,
    pods: list[dict[str, Any]] | None = None,
) -> RayJobDetail:
    del db
    base = await build_list_item(None, row)
    ws = await ws_crud.get_workspace(None, row.get("workspace_id"))
    return RayJobDetail(
        **base.model_dump(),
        workspace_display_name=ws.get("display_name") if ws else "(deleted)",
        description=row.get("description"),
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_cr_name=row.get("k8s_cr_name") or "",
        head_image=row.get("head_image") or "",
        worker_image=row.get("worker_image") or "",
        extra_fsx_mounts=[ExtraFsxMount(**m) for m in (row.get("extra_fsx_mounts") or [])],
        s3_datasets=[S3DatasetMount(**s) for s in (row.get("s3_datasets") or [])],
        entry_script_path=row.get("entry_script_path"),
        head_instance_type=row.get("head_instance_type") or "",
        head_gpu=int(row.get("head_gpu") or 0),
        head_cpu_request_millicores=int(row.get("head_cpu_request_millicores") or 0),
        head_cpu_limit_millicores=int(row.get("head_cpu_limit_millicores") or 0),
        head_memory_request_mib=int(row.get("head_memory_request_mib") or 0),
        head_memory_limit_mib=int(row.get("head_memory_limit_mib") or 0),
        head_efa=int(row.get("head_efa") or 0),
        cpu_request_millicores=int(row.get("cpu_request_millicores") or 0),
        cpu_limit_millicores=int(row.get("cpu_limit_millicores") or 0),
        memory_request_mib=int(row.get("memory_request_mib") or 0),
        memory_limit_mib=int(row.get("memory_limit_mib") or 0),
        efa_per_node=int(row.get("efa_per_node") or 0),
        max_run_hours=int(row.get("max_run_hours") or 24),
        ttl_seconds_after_finished=int(row.get("ttl_seconds_after_finished", 3600)),
        backoff_limit=int(row.get("backoff_limit") or 0),
        env=row.get("env") or {},
        env_secrets=[RayEnvSecret(**s) for s in (row.get("env_secrets") or [])],
        run_as_root=bool(row.get("run_as_root", True)),
        labels=row.get("labels") or {},
        last_condition_message=row.get("last_condition_message"),
        conditions=conditions or [],
        pods=[_pod_summary(p) for p in (pods or [])],
    )
