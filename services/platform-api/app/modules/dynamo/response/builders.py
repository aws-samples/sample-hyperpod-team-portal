"""Dynamo 响应视图构建."""

from __future__ import annotations

from typing import Any

from app.core.pod_status import summarize_pod
from app.modules.dynamo.api.schemas import DynamoDetail, DynamoListItem, DynamoS3Source
from app.modules.workspace import crud as ws_crud


def _pod_summary(p: dict[str, Any]) -> dict[str, Any]:
    meta = p.get("metadata") or {}
    status_ = p.get("status") or {}
    agg = summarize_pod(p)
    return {
        "name": meta.get("name"),
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


def _maybe_s3(d: dict[str, Any] | None) -> DynamoS3Source | None:
    return DynamoS3Source(**d) if d else None


async def build_list_item(db: Any, row: dict[str, Any]) -> DynamoListItem:
    # 不查 workspace: 列表页不用 workspace_display_name (自己维护 ws 名), 省每行一次 GetItem。
    # 详情页要用 → 由 build_detail 单独查一次 (见下)。
    del db
    phase = "Stopped" if row.get("stop_requested") else (row.get("phase") or "initializing")
    return DynamoListItem(
        id=str(row.get("id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        creator_user_id=str(row.get("creator_user_id") or ""),
        creator_display_name=row.get("creator_display_name")
        or row.get("creator_user_id")
        or "",
        name=row.get("name") or "",
        display_name=row.get("display_name") or "",
        backend_framework=row.get("backend_framework") or "sglang",
        phase=phase,
        kueue_status=row.get("kueue_status"),
        node_count=int(row.get("node_count") or 1),
        replicas=int(row.get("replicas") or 1),
        instance_type=row.get("instance_type") or "",
        gpu_per_worker=int(row.get("gpu_per_worker") or 1),
        endpoint_url=row.get("endpoint_url"),
        created_at=row.get("created_at") or "",
        last_sync_at=row.get("last_sync_at"),
    )


async def build_detail(
    db: Any,
    row: dict[str, Any],
    conditions: list[dict[str, Any]] | None = None,
    pods: list[dict[str, Any]] | None = None,
) -> DynamoDetail:
    del db
    base = await build_list_item(None, row)
    # 详情页"工作空间"栏用: 单独查一次 ws (列表路径已不查, 详见 build_list_item)。
    ws = await ws_crud.get_workspace(None, row.get("workspace_id"))
    return DynamoDetail(
        **base.model_dump(),
        workspace_display_name=ws.get("display_name") if ws else "(deleted)",
        description=row.get("description"),
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_cr_name=row.get("k8s_cr_name") or "",
        image=row.get("image") or "",
        model_source_type=row.get("model_source_type") or "fsx",
        fsx_pvc_name=row.get("fsx_pvc_name"),
        fsx_mount_path=row.get("fsx_mount_path"),
        s3=_maybe_s3(row.get("s3")),
        launch_script=row.get("launch_script"),
        cpu_request_millicores=int(row.get("cpu_request_millicores") or 0),
        cpu_limit_millicores=int(row.get("cpu_limit_millicores") or 0),
        memory_request_mib=int(row.get("memory_request_mib") or 0),
        memory_limit_mib=int(row.get("memory_limit_mib") or 0),
        efa_per_worker=int(row.get("efa_per_worker") or 0),
        run_as_root=bool(row.get("run_as_root", True)),
        labels=row.get("labels") or {},
        last_condition_message=row.get("last_condition_message"),
        conditions=conditions or [],
        pods=[_pod_summary(p) for p in (pods or [])],
    )
