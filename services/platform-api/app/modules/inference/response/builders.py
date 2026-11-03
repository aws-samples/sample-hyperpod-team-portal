"""Inference 响应视图构建 (DDB-only)."""

from __future__ import annotations

from typing import Any

from app.core.pod_status import summarize_pod
from app.modules.inference.api.schemas import (
    InferenceDetail,
    InferenceListItem,
    L2KvCacheConfig,
    ModelSourceFsx,
    ModelSourceHuggingFace,
    ModelSourceS3,
)
from app.modules.workspace import crud as ws_crud


def _associate_workloads(workloads: list[dict[str, Any]]) -> dict[str, str]:
    """{pod_name: workload_name}: 每个 Workload 的 ownerRef 里 kind=Pod 的名字 → 该 Workload 名。

    推理每 Pod 一个 pod 级 Workload (owner=该 Pod), 据此把 pod 反查到它的 Workload
    (workload 名带随机 hash, 拼不出, 必须查)。
    """
    out: dict[str, str] = {}
    for wl in workloads:
        meta = wl.get("metadata") or {}
        wl_name = meta.get("name")
        if not wl_name:
            continue
        for ref in meta.get("ownerReferences") or []:
            if ref.get("kind") == "Pod" and ref.get("name"):
                out[ref["name"]] = wl_name
    return out


def _pod_summary(p: dict[str, Any], pod_to_wl: dict[str, str]) -> dict[str, Any]:
    meta = p.get("metadata") or {}
    status_ = p.get("status") or {}
    agg = summarize_pod(p)
    name = meta.get("name")
    return {
        "name": name,
        "workload_name": pod_to_wl.get(name or ""),
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


def _maybe_fsx(d: dict[str, Any] | None) -> ModelSourceFsx | None:
    if not d:
        return None
    return ModelSourceFsx(**d)


def _maybe_s3(d: dict[str, Any] | None) -> ModelSourceS3 | None:
    if not d:
        return None
    return ModelSourceS3(**d)


def _maybe_hf(d: dict[str, Any] | None) -> ModelSourceHuggingFace | None:
    if not d:
        return None
    return ModelSourceHuggingFace(**d)


def _l2(d: dict[str, Any] | None) -> L2KvCacheConfig:
    return L2KvCacheConfig(**d) if d else L2KvCacheConfig()


async def build_list_item(
    db: Any, row: dict[str, Any]
) -> InferenceListItem:
    """组 inference 列表项. creator_display_name 冗余读 row.

    不查 workspace: 列表页不用 workspace_display_name (自己维护 ws 名), 省每行一次 GetItem。
    详情页要用 → 由 build_detail 单独查一次 (见下)。
    """
    del db
    # stop_requested 时 phase 强制 Stopped: phase 是 informer 领域字段, 停止删 CR
    # 期间 informer 会把 mark_stopped 写的 Stopped 冲回 CR 派生值 (DeploymentInProgress),
    # 致 UI 不显示停止。stop_requested 是平台哨兵, informer 不碰, 据它纠正显示。
    phase = "Stopped" if row.get("stop_requested") else (row.get("phase") or "Pending")
    return InferenceListItem(
        id=str(row.get("id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        creator_user_id=str(row.get("creator_user_id") or ""),
        creator_display_name=row.get("creator_display_name")
        or row.get("creator_user_id")
        or "",
        name=row.get("name") or "",
        display_name=row.get("display_name") or "",
        framework=row.get("framework") or "sglang",
        model_name=row.get("model_name") or "",
        model_source_type=row.get("model_source_type") or "",
        phase=phase,
        kueue_status=row.get("kueue_status"),
        replicas=int(row.get("replicas") or 1),
        gpu_per_replica=int(row.get("gpu_per_replica") or 1),
        instance_type=row.get("instance_type") or "",
        endpoint_url=row.get("endpoint_url"),
        created_at=row.get("created_at") or "",
        ended_at=row.get("ended_at"),
        last_sync_at=row.get("last_sync_at"),
    )


async def build_detail(
    db: Any,
    row: dict[str, Any],
    conditions: list[dict[str, Any]] | None = None,
    pods: list[dict[str, Any]] | None = None,
    workloads: list[dict[str, Any]] | None = None,
) -> InferenceDetail:
    del db
    pod_to_wl = _associate_workloads(workloads or [])
    base = await build_list_item(None, row)
    # 详情页"工作空间"栏用: 单独查一次 ws (列表路径已不查, 详见 build_list_item)。
    ws = await ws_crud.get_workspace(None, row.get("workspace_id"))
    return InferenceDetail(
        **base.model_dump(),
        workspace_display_name=ws.get("display_name") if ws else "(deleted)",
        description=row.get("description"),
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_endpoint_name=row.get("k8s_endpoint_name") or "",
        model_mount_path=row.get("model_mount_path") or "/opt/ml/model",
        image=row.get("image") or "",
        invocation_endpoint=row.get("invocation_endpoint") or "",
        container_port=int(row.get("container_port") or 8000),
        sglang_extra_args=row.get("sglang_extra_args") or [],
        launch_script=row.get("launch_script"),
        cpu_request_millicores=int(row.get("cpu_request_millicores") or 0),
        cpu_limit_millicores=int(row.get("cpu_limit_millicores") or 0),
        memory_request_mib=int(row.get("memory_request_mib") or 0),
        memory_limit_mib=int(row.get("memory_limit_mib") or 0),
        fsx=_maybe_fsx(row.get("fsx")),
        s3=_maybe_s3(row.get("s3")),
        huggingface=_maybe_hf(row.get("huggingface")),
        routing_strategy=row.get("routing_strategy") or "roundrobin",
        l2_kv_cache=_l2(row.get("l2_kv_cache")),
        metrics_enabled=bool(row.get("metrics_enabled", True)),
        public_endpoint=bool(row.get("public_endpoint", False)),
        alb_dns=row.get("alb_dns"),
        labels=row.get("labels") or {},
        env=row.get("env") or {},
        last_condition_message=row.get("last_condition_message"),
        conditions=conditions or [],
        pods=[_pod_summary(p, pod_to_wl) for p in (pods or [])],
    )
