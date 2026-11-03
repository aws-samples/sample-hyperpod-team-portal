"""llm-d 响应视图构建 (分支B)."""

from __future__ import annotations

from typing import Any

from app.core.pod_status import summarize_pod
from app.modules.llmd.api.schemas import LlmdDetail, LlmdListItem
from app.modules.workspace import crud as ws_crud


def _pod_group(pod_name: str, role: str, base_name: str) -> str | None:
    """从 LWS Pod 名解析副本组序号。gateway/无法解析 → None。

    LWS Pod 名: leader=<base>-multi-<group>, worker=<base>-multi-<group>-<podidx>。
    去掉 <base>-multi- 前缀后取第一段数字 = group。
    """
    if role == "gateway":
        return None
    prefix = f"{base_name}-multi-"
    if not pod_name.startswith(prefix):
        return None
    rest = pod_name[len(prefix):]
    head = rest.split("-", 1)[0]
    return head if head.isdigit() else None


def _associate_workloads(workloads: list[dict[str, Any]]) -> dict[str, str]:
    """{pod_name: workload_name}: 每个 Workload 的 ownerRef 里 kind=Pod 的名字 → 该 Workload 名。

    LWS Workload owner 直接列出组内 leader+worker Pod; gateway Workload owner=单个 gateway Pod。
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


def _pod_summary(
    p: dict[str, Any], base_name: str, pod_to_wl: dict[str, str]
) -> dict[str, Any]:
    meta = p.get("metadata") or {}
    labels = meta.get("labels") or {}
    status_ = p.get("status") or {}
    agg = summarize_pod(p)
    name = meta.get("name")
    # role: gateway (Deployment pod, 无 role label) / leader / worker (LWS pod label)
    role = labels.get("role") or ("gateway" if "gateway" in (name or "") else "")
    return {
        "name": name,
        "role": role,
        "group": _pod_group(name or "", role, base_name),
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


async def build_list_item(db: Any, row: dict[str, Any]) -> LlmdListItem:
    # 不查 workspace: 列表页不用 workspace_display_name (省每行一次 GetItem)。
    del db
    phase = "Stopped" if row.get("stop_requested") else (row.get("phase") or "initializing")
    return LlmdListItem(
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
        replicas=int(row.get("replicas") or 1),
        nodes_per_replica=int(row.get("nodes_per_replica") or 2),
        gpu_instance_type=row.get("gpu_instance_type") or "",
        gpu_per_pod=int(row.get("gpu_per_pod") or 1),
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
) -> LlmdDetail:
    del db
    pod_to_wl = _associate_workloads(workloads or [])
    base_name = row.get("name") or ""
    base = await build_list_item(None, row)
    # 详情页"工作空间"栏用: 单独查一次 ws (列表路径已不查)。
    ws = await ws_crud.get_workspace(None, row.get("workspace_id"))
    return LlmdDetail(
        **base.model_dump(),
        workspace_display_name=ws.get("display_name") if ws else "(deleted)",
        description=row.get("description"),
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_name=row.get("k8s_name") or "",  # CR base 名; gateway svc 加 -gateway 后缀
        model_source_type=row.get("model_source_type") or "fsx",
        launch_script=row.get("launch_script") or "",
        model_pvc=row.get("model_pvc") or "",
        s3_bucket=row.get("s3_bucket"),
        s3_prefix=row.get("s3_prefix"),
        gateway_instance_type=row.get("gateway_instance_type")
        or row.get("gpu_instance_type")
        or "",
        efa_per_pod=int(row.get("efa_per_pod") or 0),
        cpu_request_millicores=int(row.get("cpu_request_millicores") or 4000),
        cpu_limit_millicores=int(row.get("cpu_limit_millicores") or 4000),
        memory_request_mib=int(row.get("memory_request_mib") or 16384),
        memory_limit_mib=int(row.get("memory_limit_mib") or 16384),
        gateway_image=row.get("gateway_image") or "",
        sglang_image=row.get("sglang_image") or "",
        gateway_replicas=int(row.get("gateway_replicas") or 1),
        gateway_extra_args=row.get("gateway_extra_args") or [],
        gateway_cpu_request_millicores=int(row.get("gateway_cpu_request_millicores") or 1000),
        gateway_cpu_limit_millicores=int(row.get("gateway_cpu_limit_millicores") or 4000),
        gateway_memory_request_mib=int(row.get("gateway_memory_request_mib") or 2048),
        gateway_memory_limit_mib=int(row.get("gateway_memory_limit_mib") or 8192),
        expose_alb=bool(row.get("expose_alb") or False),
        # sync=true 时由 sync 实时填; 纯读 DDB 路径为空 (前端据此显示"就绪中")
        alb_dns=row.get("alb_dns"),
        labels=row.get("labels") or {},
        last_condition_message=row.get("last_condition_message"),
        conditions=conditions or [],
        pods=[_pod_summary(p, base_name, pod_to_wl) for p in (pods or [])],
    )
