"""llm-d CRUD (DDB-only, 复用 ResourceIndex 表 resource_type='llmd' — 分支B).

k8s_name = CR base 名 (= row["name"]); 派生资源加后缀: gateway svc/deploy
=<k8s_name>-gateway、LWS=<k8s_name>-multi、pod label instance=<k8s_name>。
存量老行曾存 "<name>-gateway", 未迁移。

phase/kueue_status/endpoint_url 由 Go platform-controller 派生写, Python 侧只 create 写初值
+ 整行 put 时读出写回 (防冲掉 controller 值)。
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import tables as _tables
from app.core.priority_defaults import default_priority_class
from app.modules.shared.kueue_status import KUEUE_FINISHED
from app.repositories import resource_index as ri_repo

_RESOURCE_KIND = "LeaderWorkerSet"

# 列表页需要全量数据做前端筛选/统计 (Excel 式列筛选), ri_repo 默认 limit=200 会截断。
# 与 training crud 同口径 (见 training/persistence/crud.py _LIST_LIMIT)。
_LIST_LIMIT = 5000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _ri_to_llmd(item: dict[str, Any]) -> dict[str, Any]:
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
        "k8s_name": item.get("k8s_name"),
        "model_source_type": md.get("model_source_type") or "fsx",
        "launch_script": md.get("launch_script"),
        "model_pvc": md.get("model_pvc"),
        "s3_bucket": md.get("s3_bucket"),
        "s3_prefix": md.get("s3_prefix"),
        "gpu_instance_type": md.get("gpu_instance_type"),
        # 旧行无独立 gateway 机型 → 回退 worker 机型 (旧行 gateway 落 worker 同机)
        "gateway_instance_type": md.get("gateway_instance_type")
        or md.get("gpu_instance_type"),
        "replicas": int(md.get("replicas") or 1),
        "nodes_per_replica": int(md.get("nodes_per_replica") or 2),
        "gpu_per_pod": int(md.get("gpu_per_pod") or 1),
        "efa_per_pod": int(md.get("efa_per_pod") or 0),
        "cpu_request_millicores": int(md.get("cpu_request_millicores") or 4000),
        "cpu_limit_millicores": int(md.get("cpu_limit_millicores") or 4000),
        "memory_request_mib": int(md.get("memory_request_mib") or 16384),
        "memory_limit_mib": int(md.get("memory_limit_mib") or 16384),
        "gateway_image": md.get("gateway_image"),
        "sglang_image": md.get("sglang_image"),
        "gateway_replicas": int(md.get("gateway_replicas") or 1),
        "gateway_extra_args": md.get("gateway_extra_args") or [],
        "gateway_cpu_request_millicores": int(md.get("gateway_cpu_request_millicores") or 1000),
        "gateway_cpu_limit_millicores": int(md.get("gateway_cpu_limit_millicores") or 4000),
        "gateway_memory_request_mib": int(md.get("gateway_memory_request_mib") or 2048),
        "gateway_memory_limit_mib": int(md.get("gateway_memory_limit_mib") or 8192),
        # 存量老行没这个键 → 读出 False, 不需要迁移
        "expose_alb": bool(md.get("expose_alb") or False),
        "labels": md.get("labels") or {},
        # phase/kueue_status/endpoint_url 由 Go controller 写
        "phase": md.get("phase") or "initializing",
        # informer 从 CR label 派生; create 写初值 (worker 空窗也有值)。
        "priority_class": md.get("priority_class"),
        "kueue_status": md.get("kueue_status"),
        "stop_requested": md.get("stop_requested"),
        "endpoint_url": md.get("endpoint_url"),
        "last_condition_message": md.get("last_condition_message"),
        "status_detail": md.get("status_detail"),
        "last_sync_at": md.get("last_sync_at"),
        # log_streams: 任务 finished 后缓存的 CloudWatch stream 列表 (懒加载, 见
        # get_or_cache_streams)。与 _llmd_to_md 写侧对称, 防整行 put 抹缓存。
        "log_streams": md.get("log_streams"),
        # 与写侧对称, 否则整行 put 会抹掉
        "ended_at": md.get("ended_at"),
        "created_at": item.get("created_at"),
        "updated_at": md.get("updated_at") or item.get("created_at"),
    }


def _llmd_to_md(llmd: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "name": llmd.get("name"),
            "description": llmd.get("description"),
            "model_source_type": llmd.get("model_source_type"),
            "launch_script": llmd.get("launch_script"),
            "model_pvc": llmd.get("model_pvc"),
            "s3_bucket": llmd.get("s3_bucket"),
            "s3_prefix": llmd.get("s3_prefix"),
            "gpu_instance_type": llmd.get("gpu_instance_type"),
            "gateway_instance_type": llmd.get("gateway_instance_type"),
            "replicas": llmd.get("replicas"),
            "nodes_per_replica": llmd.get("nodes_per_replica"),
            "gpu_per_pod": llmd.get("gpu_per_pod"),
            "efa_per_pod": llmd.get("efa_per_pod"),
            "cpu_request_millicores": llmd.get("cpu_request_millicores"),
            "cpu_limit_millicores": llmd.get("cpu_limit_millicores"),
            "memory_request_mib": llmd.get("memory_request_mib"),
            "memory_limit_mib": llmd.get("memory_limit_mib"),
            "gateway_image": llmd.get("gateway_image"),
            "sglang_image": llmd.get("sglang_image"),
            "gateway_replicas": llmd.get("gateway_replicas"),
            "gateway_extra_args": llmd.get("gateway_extra_args"),
            "gateway_cpu_request_millicores": llmd.get("gateway_cpu_request_millicores"),
            "gateway_cpu_limit_millicores": llmd.get("gateway_cpu_limit_millicores"),
            "gateway_memory_request_mib": llmd.get("gateway_memory_request_mib"),
            "gateway_memory_limit_mib": llmd.get("gateway_memory_limit_mib"),
            "expose_alb": bool(llmd.get("expose_alb") or False),  # 与 _ri_to_llmd 对称
            "labels": llmd.get("labels") or {},
            "phase": llmd.get("phase"),
            # 以下字段 informer / Go controller 写; 与 _ri_to_llmd 读出对称, 整行 put 不丢。
            "priority_class": llmd.get("priority_class"),
            "kueue_status": llmd.get("kueue_status"),
            "stop_requested": llmd.get("stop_requested"),
            "endpoint_url": llmd.get("endpoint_url"),
            "last_condition_message": llmd.get("last_condition_message"),
            "status_detail": llmd.get("status_detail"),
            "last_sync_at": llmd.get("last_sync_at"),
            # log_streams: 与 _ri_to_llmd 读出对称 (懒加载缓存, 见 get_or_cache_streams)。
            "log_streams": llmd.get("log_streams"),
            # 与 _ri_to_llmd 读出对称
            "ended_at": llmd.get("ended_at"),
            "creator_display_name": llmd.get("creator_display_name"),
            "updated_at": llmd.get("updated_at"),
        }.items()
        if v is not None
    }


async def _find_by_id(resource_id: str) -> dict[str, Any] | None:
    # 精确走 resource_id-index GSI (O(1)); 校验 resource_type 防误命中别类型行。
    it = await ri_repo.get_by_resource_id(resource_id)
    if it and it.get("resource_type") == _tables.RESOURCE_TYPE_LLMD:
        return it
    return None


async def get(db: Any, id_: Any) -> dict[str, Any] | None:
    del db
    item = await _find_by_id(str(id_))
    return _ri_to_llmd(item) if item else None


async def list_by_workspace(
    db: Any,
    ws_id: Any,
    phase: str | None = None,
    creator_user_id: Any | None = None,
) -> list[dict[str, Any]]:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_LLMD, limit=_LIST_LIMIT
    )
    out: list[dict[str, Any]] = []
    for it in items:
        if creator_user_id is not None and it.get("creator_user_id") != str(
            creator_user_id
        ):
            continue
        md = it.get("metadata") or {}
        if phase and md.get("phase") != phase:
            continue
        out.append(_ri_to_llmd(it))
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
    k8s_name: str,
    model_source_type: str,
    launch_script: str,
    model_pvc: str,
    s3_bucket: str | None,
    s3_prefix: str | None,
    gpu_instance_type: str,
    gateway_instance_type: str,
    replicas: int,
    nodes_per_replica: int,
    gpu_per_pod: int,
    efa_per_pod: int,
    cpu_request_millicores: int,
    cpu_limit_millicores: int,
    memory_request_mib: int,
    memory_limit_mib: int,
    gateway_image: str,
    sglang_image: str,
    gateway_replicas: int,
    gateway_extra_args: list[str],
    gateway_cpu_request_millicores: int,
    gateway_cpu_limit_millicores: int,
    gateway_memory_request_mib: int,
    gateway_memory_limit_mib: int,
    expose_alb: bool = False,
    labels: dict[str, str],
) -> dict[str, Any]:
    del db
    resource_id = _new_id()
    now = _now_iso()
    llmd = {
        "id": resource_id,
        "workspace_id": str(workspace_id),
        "creator_user_id": str(creator_user_id),
        "creator_display_name": creator_display_name or str(creator_user_id),
        "name": name,
        "display_name": display_name,
        "description": description,
        "k8s_namespace": k8s_namespace,
        "k8s_name": k8s_name,
        "model_source_type": model_source_type,
        "launch_script": launch_script,
        "model_pvc": model_pvc,
        "s3_bucket": s3_bucket,
        "s3_prefix": s3_prefix,
        "gpu_instance_type": gpu_instance_type,
        "gateway_instance_type": gateway_instance_type,
        "replicas": replicas,
        "nodes_per_replica": nodes_per_replica,
        "gpu_per_pod": gpu_per_pod,
        "efa_per_pod": efa_per_pod,
        "cpu_request_millicores": cpu_request_millicores,
        "cpu_limit_millicores": cpu_limit_millicores,
        "memory_request_mib": memory_request_mib,
        "memory_limit_mib": memory_limit_mib,
        "gateway_image": gateway_image,
        "sglang_image": sglang_image,
        "gateway_replicas": gateway_replicas,
        "gateway_extra_args": gateway_extra_args,
        "gateway_cpu_request_millicores": gateway_cpu_request_millicores,
        "gateway_cpu_limit_millicores": gateway_cpu_limit_millicores,
        "expose_alb": expose_alb,
        "gateway_memory_request_mib": gateway_memory_request_mib,
        "gateway_memory_limit_mib": gateway_memory_limit_mib,
        "labels": labels,
        "phase": "initializing",
        "priority_class": default_priority_class("llmd"),
        "endpoint_url": None,
        "created_at": now,
        "updated_at": now,
    }
    await ri_repo.upsert_resource(
        workspace_id=str(workspace_id),
        resource_type=_tables.RESOURCE_TYPE_LLMD,
        resource_id=resource_id,
        creator_user_id=str(creator_user_id),
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_name,
        resource_kind=_RESOURCE_KIND,
        display_name=display_name,
        metadata=_llmd_to_md(llmd),
    )
    return llmd


async def mark_stopped(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """停止: phase=Stopped + 保留 DDB 行 (照 dynamo)。删资源组后 LWS 回收 pod。"""
    del db
    ended = _now_iso()  # 停止即结束, 否则前端按当前时间算, 时长一直涨
    row["phase"] = "Stopped"
    row["endpoint_url"] = None
    row["kueue_status"] = KUEUE_FINISHED
    row["stop_requested"] = True
    row["ended_at"] = ended
    await ri_repo.mark_stopped_inference(
        row["workspace_id"], row["id"], _tables.RESOURCE_TYPE_LLMD, ended_at=ended
    )
    await ri_repo.clear_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_LLMD, row["id"]
    )
    return row


async def delete(db: Any, row: dict[str, Any]) -> None:
    del db
    await ri_repo.delete_resource(
        row["workspace_id"], _tables.RESOURCE_TYPE_LLMD, row["id"]
    )
