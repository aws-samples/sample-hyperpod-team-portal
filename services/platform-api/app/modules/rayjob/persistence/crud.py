"""RayJob CRUD (DDB ResourceIndex, resource_type='rayjob'). 照 dynamo/persistence/crud.py。

phase/kueue_status 由 Go controller 派生写; Python 只 create 写初值, 整行 put 时读出写回。
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import tables as _tables
from app.modules.shared.kueue_status import KUEUE_FINISHED
from app.repositories import resource_index as ri_repo

_RESOURCE_KIND = "RayJob"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _ri_to_ray(item: dict[str, Any]) -> dict[str, Any]:
    md = dict(item.get("metadata") or {})
    return {
        "id": item.get("resource_id"),
        "workspace_id": item.get("workspace_id"),
        "creator_user_id": item.get("creator_user_id"),
        "creator_display_name": md.get("creator_display_name")
        or item.get("creator_user_id"),
        "name": md.get("name") or item.get("display_name"),
        "display_name": item.get("display_name"),
        "description": md.get("description"),
        "k8s_namespace": item.get("k8s_namespace"),
        "k8s_cr_name": item.get("k8s_name"),
        "head_image": md.get("head_image") or "",
        "worker_image": md.get("worker_image") or "",
        "extra_fsx_mounts": md.get("extra_fsx_mounts") or [],
        "s3_datasets": md.get("s3_datasets") or [],
        "entry_script_path": md.get("entry_script_path"),
        "worker_replicas": int(md.get("worker_replicas") or 1),
        "head_instance_type": md.get("head_instance_type") or "",
        "head_gpu": int(md.get("head_gpu") or 0),
        "head_cpu_request_millicores": int(md.get("head_cpu_request_millicores") or 0),
        "head_cpu_limit_millicores": int(md.get("head_cpu_limit_millicores") or 0),
        "head_memory_request_mib": int(md.get("head_memory_request_mib") or 0),
        "head_memory_limit_mib": int(md.get("head_memory_limit_mib") or 0),
        "head_efa": int(md.get("head_efa") or 0),
        "worker_instance_type": md.get("worker_instance_type") or "",
        "gpu_per_node": int(md.get("gpu_per_node") or 1),
        "cpu_request_millicores": int(md.get("cpu_request_millicores") or 0),
        "cpu_limit_millicores": int(md.get("cpu_limit_millicores") or 0),
        "memory_request_mib": int(md.get("memory_request_mib") or 0),
        "memory_limit_mib": int(md.get("memory_limit_mib") or 0),
        "efa_per_node": int(md.get("efa_per_node") or 0),
        "max_run_hours": int(md.get("max_run_hours") or 24),
        "ttl_seconds_after_finished": int(md.get("ttl_seconds_after_finished", 3600)),
        "backoff_limit": int(md.get("backoff_limit") or 0),
        "env": md.get("env") or {},
        "env_secrets": md.get("env_secrets") or [],
        "run_as_root": bool(md.get("run_as_root", True)),
        "labels": md.get("labels") or {},
        "phase": md.get("phase") or "initializing",
        "ray_cluster_name": md.get("ray_cluster_name"),
        "log_streams": md.get("log_streams"),
        "kueue_status": md.get("kueue_status"),
        "stop_requested": md.get("stop_requested"),
        "last_condition_message": md.get("last_condition_message"),
        "status_detail": md.get("status_detail"),
        "last_sync_at": md.get("last_sync_at"),
        # started_at/ended_at: controller 从 CR status.startTime/endTime 派生写入 (OwnsLifecycleTimes),
        # 供前端算"运行时长" = (ended_at ?? now) - started_at。未就绪为 None。
        "started_at": md.get("started_at"),
        "ended_at": md.get("ended_at"),
        "created_at": item.get("created_at"),
        "updated_at": md.get("updated_at") or item.get("created_at"),
    }


def _ray_to_md(ray: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "name": ray.get("name"),
            "description": ray.get("description"),
            "head_image": ray.get("head_image"),
            "worker_image": ray.get("worker_image"),
            "extra_fsx_mounts": ray.get("extra_fsx_mounts") or [],
            "s3_datasets": ray.get("s3_datasets") or [],
            "entry_script_path": ray.get("entry_script_path"),
            "worker_replicas": ray.get("worker_replicas"),
            "head_instance_type": ray.get("head_instance_type"),
            "head_gpu": ray.get("head_gpu"),
            "head_cpu_request_millicores": ray.get("head_cpu_request_millicores"),
            "head_cpu_limit_millicores": ray.get("head_cpu_limit_millicores"),
            "head_memory_request_mib": ray.get("head_memory_request_mib"),
            "head_memory_limit_mib": ray.get("head_memory_limit_mib"),
            "head_efa": ray.get("head_efa"),
            "worker_instance_type": ray.get("worker_instance_type"),
            "gpu_per_node": ray.get("gpu_per_node"),
            "cpu_request_millicores": ray.get("cpu_request_millicores"),
            "cpu_limit_millicores": ray.get("cpu_limit_millicores"),
            "memory_request_mib": ray.get("memory_request_mib"),
            "memory_limit_mib": ray.get("memory_limit_mib"),
            "efa_per_node": ray.get("efa_per_node"),
            "max_run_hours": ray.get("max_run_hours"),
            "ttl_seconds_after_finished": ray.get("ttl_seconds_after_finished"),
            "backoff_limit": ray.get("backoff_limit"),
            "env": ray.get("env") or {},
            "env_secrets": ray.get("env_secrets") or [],
            "run_as_root": ray.get("run_as_root"),
            "labels": ray.get("labels") or {},
            "phase": ray.get("phase"),
            "ray_cluster_name": ray.get("ray_cluster_name"),
            "log_streams": ray.get("log_streams"),
            "kueue_status": ray.get("kueue_status"),
            "stop_requested": ray.get("stop_requested"),
            "last_condition_message": ray.get("last_condition_message"),
            "status_detail": ray.get("status_detail"),
            "last_sync_at": ray.get("last_sync_at"),
            "creator_display_name": ray.get("creator_display_name"),
            "updated_at": ray.get("updated_at"),
        }.items()
        if v is not None
    }


async def _find_by_id(resource_id: str) -> dict[str, Any] | None:
    it = await ri_repo.get_by_resource_id(resource_id)
    if it and it.get("resource_type") == _tables.RESOURCE_TYPE_RAYJOB:
        return it
    return None


async def get(db: Any, id_: Any) -> dict[str, Any] | None:
    del db
    item = await _find_by_id(str(id_))
    return _ri_to_ray(item) if item else None


async def list_by_workspace(
    db: Any,
    ws_id: Any,
    phase: str | None = None,
    creator_user_id: Any | None = None,
) -> list[dict[str, Any]]:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_RAYJOB
    )
    # scope=mine (creator_user_id 非 None): 结果 = 我创建的 ∪ 分享给我的。
    # scope=all (None): 不过滤 creator, 沿用原行为。
    shared_ids: set[str] = set()
    if creator_user_id is not None:
        from app.modules.sharing import visibility
        shared_ids = await visibility.shared_res_ids(
            str(ws_id), str(creator_user_id), _tables.RESOURCE_TYPE_RAYJOB
        )
    out: list[dict[str, Any]] = []
    for it in items:
        if creator_user_id is not None:
            mine = it.get("creator_user_id") == str(creator_user_id)
            shared = it.get("resource_id") in shared_ids
            if not (mine or shared):
                continue
        md = it.get("metadata") or {}
        if phase and md.get("phase") != phase:
            continue
        out.append(_ri_to_ray(it))
    return out


async def create(
    db: Any,
    *,
    workspace_id: Any,
    creator_user_id: Any,
    creator_display_name: str | None,
    name: str,
    display_name: str,
    description: str | None,
    k8s_namespace: str,
    k8s_cr_name: str,
    head_image: str,
    worker_image: str,
    extra_fsx_mounts: list[dict[str, Any]],
    s3_datasets: list[dict[str, Any]],
    entry_script_path: str,
    worker_replicas: int,
    head_instance_type: str,
    head_gpu: int,
    head_cpu_request_millicores: int,
    head_cpu_limit_millicores: int,
    head_memory_request_mib: int,
    head_memory_limit_mib: int,
    head_efa: int,
    worker_instance_type: str,
    gpu_per_node: int,
    cpu_request_millicores: int,
    cpu_limit_millicores: int,
    memory_request_mib: int,
    memory_limit_mib: int,
    efa_per_node: int,
    max_run_hours: int,
    ttl_seconds_after_finished: int,
    backoff_limit: int,
    env: dict[str, str],
    env_secrets: list[dict[str, Any]],
    run_as_root: bool,
    labels: dict[str, str],
) -> dict[str, Any]:
    del db
    resource_id = _new_id()
    now = _now_iso()
    ray = {
        "id": resource_id,
        "workspace_id": str(workspace_id),
        "creator_user_id": str(creator_user_id),
        "creator_display_name": creator_display_name or str(creator_user_id),
        "name": name,
        "display_name": display_name,
        "description": description,
        "k8s_namespace": k8s_namespace,
        "k8s_cr_name": k8s_cr_name,
        "head_image": head_image,
        "worker_image": worker_image,
        "extra_fsx_mounts": extra_fsx_mounts,
        "s3_datasets": s3_datasets,
        "entry_script_path": entry_script_path,
        "worker_replicas": worker_replicas,
        "head_instance_type": head_instance_type,
        "head_gpu": head_gpu,
        "head_cpu_request_millicores": head_cpu_request_millicores,
        "head_cpu_limit_millicores": head_cpu_limit_millicores,
        "head_memory_request_mib": head_memory_request_mib,
        "head_memory_limit_mib": head_memory_limit_mib,
        "head_efa": head_efa,
        "worker_instance_type": worker_instance_type,
        "gpu_per_node": gpu_per_node,
        "cpu_request_millicores": cpu_request_millicores,
        "cpu_limit_millicores": cpu_limit_millicores,
        "memory_request_mib": memory_request_mib,
        "memory_limit_mib": memory_limit_mib,
        "efa_per_node": efa_per_node,
        "max_run_hours": max_run_hours,
        "ttl_seconds_after_finished": ttl_seconds_after_finished,
        "backoff_limit": backoff_limit,
        "env": env,
        "env_secrets": env_secrets,
        "run_as_root": run_as_root,
        "labels": labels,
        "phase": "initializing",
        "created_at": now,
        "updated_at": now,
    }
    await ri_repo.upsert_resource(
        workspace_id=str(workspace_id),
        resource_type=_tables.RESOURCE_TYPE_RAYJOB,
        resource_id=resource_id,
        creator_user_id=str(creator_user_id),
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_cr_name,
        resource_kind=_RESOURCE_KIND,
        display_name=display_name,
        metadata=_ray_to_md(ray),
    )
    return ray


async def mark_stopped(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """停止: phase=Stopped + 保留 DDB 行 (照 dynamo)。删 CR 后 KubeRay 回收 pod。"""
    del db
    row["phase"] = "Stopped"
    row["kueue_status"] = KUEUE_FINISHED
    row["stop_requested"] = True
    await ri_repo.mark_stopped_inference(
        row["workspace_id"], row["id"], _tables.RESOURCE_TYPE_RAYJOB
    )
    await ri_repo.clear_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_RAYJOB, row["id"]
    )
    return row


async def delete(db: Any, row: dict[str, Any]) -> None:
    del db
    await ri_repo.delete_resource(
        row["workspace_id"], _tables.RESOURCE_TYPE_RAYJOB, row["id"]
    )
