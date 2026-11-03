"""Dynamo CRUD (DDB-only, 复用 ResourceIndex 表 resource_type='dynamo').

K8s CR 是 SoT; DDB ResourceIndex 写索引。镜像 inference/persistence/crud.py。

★ 两个必留口 (后续监控/日志/终端/ALB 靠它, 不留则返工):
    - k8s_cr_name: pod 定位锚点 (= CR 名; grove pod label nvidia.com/dynamo-graph-deployment-name)
    - endpoint_url: 最小切片留空字段位, 后续 ALB 回读只填值不改结构

phase/kueue_status/endpoint_url 由 Go platform-controller 派生写 (derive_dynamo.go),
Python 侧只 create 写初值 + 整行 put 时读出写回 (防冲掉 controller 值)。
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import tables as _tables
from app.modules.shared.kueue_status import KUEUE_FINISHED
from app.repositories import resource_index as ri_repo

_RESOURCE_KIND = "DynamoGraphDeployment"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _ri_to_dyn(item: dict[str, Any]) -> dict[str, Any]:
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
        # ★ pod 定位锚点 (= CR 名)
        "k8s_cr_name": item.get("k8s_name"),
        # 引擎
        "backend_framework": md.get("backend_framework") or "sglang",
        "image": md.get("image"),
        # 模型来源 (授权反查真值)
        "model_source_type": md.get("model_source_type") or "fsx",
        "fsx_pvc_name": md.get("fsx_pvc_name"),
        "fsx_mount_path": md.get("fsx_mount_path"),
        "s3": md.get("s3"),
        "launch_script": md.get("launch_script"),
        # 多机
        "node_count": int(md.get("node_count") or 1),
        "replicas": int(md.get("replicas") or 1),
        # 资源 (模板锁单节点规格)
        "instance_type": md.get("instance_type"),
        "gpu_per_worker": int(md.get("gpu_per_worker") or 1),
        "cpu_request_millicores": int(md.get("cpu_request_millicores") or 0),
        "cpu_limit_millicores": int(md.get("cpu_limit_millicores") or 0),
        "memory_request_mib": int(md.get("memory_request_mib") or 0),
        "memory_limit_mib": int(md.get("memory_limit_mib") or 0),
        "efa_per_worker": int(md.get("efa_per_worker") or 0),
        "run_as_root": bool(md.get("run_as_root", True)),
        "labels": md.get("labels") or {},
        # 状态 (Go controller 写)
        "phase": md.get("phase") or "initializing",
        "kueue_status": md.get("kueue_status"),
        "stop_requested": md.get("stop_requested"),
        # ★ 空字段位, 后续 ALB 回读填
        "endpoint_url": md.get("endpoint_url"),
        "last_condition_message": md.get("last_condition_message"),
        "status_detail": md.get("status_detail"),
        # log_streams (任务 finished 后缓存的 CloudWatch stream 列表): 与
        # _dyn_to_md 写入对称, 否则业务/controller 整行 put 会把缓存抹掉。
        "log_streams": md.get("log_streams"),
        "last_sync_at": md.get("last_sync_at"),
        "created_at": item.get("created_at"),
        "updated_at": md.get("updated_at") or item.get("created_at"),
    }


def _dyn_to_md(dyn: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "name": dyn.get("name"),
            "description": dyn.get("description"),
            "backend_framework": dyn.get("backend_framework"),
            "image": dyn.get("image"),
            "model_source_type": dyn.get("model_source_type"),
            "fsx_pvc_name": dyn.get("fsx_pvc_name"),
            "fsx_mount_path": dyn.get("fsx_mount_path"),
            "s3": dyn.get("s3"),
            "launch_script": dyn.get("launch_script"),
            "node_count": dyn.get("node_count"),
            "replicas": dyn.get("replicas"),
            "instance_type": dyn.get("instance_type"),
            "gpu_per_worker": dyn.get("gpu_per_worker"),
            "cpu_request_millicores": dyn.get("cpu_request_millicores"),
            "cpu_limit_millicores": dyn.get("cpu_limit_millicores"),
            "memory_request_mib": dyn.get("memory_request_mib"),
            "memory_limit_mib": dyn.get("memory_limit_mib"),
            "efa_per_worker": dyn.get("efa_per_worker"),
            "run_as_root": dyn.get("run_as_root"),
            "labels": dyn.get("labels") or {},
            "phase": dyn.get("phase"),
            # 以下字段 Go controller 写; 与 _ri_to_dyn 读出对称, 整行 put 不丢。
            "kueue_status": dyn.get("kueue_status"),
            "stop_requested": dyn.get("stop_requested"),
            "endpoint_url": dyn.get("endpoint_url"),
            "last_condition_message": dyn.get("last_condition_message"),
            "status_detail": dyn.get("status_detail"),
            # log_streams: 与 _ri_to_dyn 读出对称 (懒加载缓存, 见 get_or_cache_streams)。
            "log_streams": dyn.get("log_streams"),
            "last_sync_at": dyn.get("last_sync_at"),
            "creator_display_name": dyn.get("creator_display_name"),
            "updated_at": dyn.get("updated_at"),
        }.items()
        if v is not None
    }


async def _find_by_id(resource_id: str) -> dict[str, Any] | None:
    # 精确走 resource_id-index GSI (O(1)), 替代 list_by_type 全类型分区扫。
    # 校验 resource_type: id 全局唯一, 但防御性确保命中的确是 dynamo 行 (原
    # list_by_type 隐含只在本类型找, 保持等价语义)。
    it = await ri_repo.get_by_resource_id(resource_id)
    if it and it.get("resource_type") == _tables.RESOURCE_TYPE_DYNAMO:
        return it
    return None


async def get(db: Any, id_: Any) -> dict[str, Any] | None:
    del db
    item = await _find_by_id(str(id_))
    return _ri_to_dyn(item) if item else None


async def list_by_workspace(
    db: Any,
    ws_id: Any,
    phase: str | None = None,
    creator_user_id: Any | None = None,
) -> list[dict[str, Any]]:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_DYNAMO
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
        out.append(_ri_to_dyn(it))
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
    backend_framework: str,
    image: str,
    model_source_type: str,
    fsx_pvc_name: str | None,
    fsx_mount_path: str | None,
    s3: dict[str, Any] | None,
    launch_script: str,
    node_count: int,
    replicas: int,
    instance_type: str,
    gpu_per_worker: int,
    cpu_request_millicores: int,
    cpu_limit_millicores: int,
    memory_request_mib: int,
    memory_limit_mib: int,
    efa_per_worker: int,
    run_as_root: bool,
    labels: dict[str, str],
) -> dict[str, Any]:
    del db
    resource_id = _new_id()
    now = _now_iso()
    dyn = {
        "id": resource_id,
        "workspace_id": str(workspace_id),
        "creator_user_id": str(creator_user_id),
        "creator_display_name": creator_display_name or str(creator_user_id),
        "name": name,
        "display_name": display_name,
        "description": description,
        "k8s_namespace": k8s_namespace,
        "k8s_cr_name": k8s_cr_name,
        "backend_framework": backend_framework,
        "image": image,
        "model_source_type": model_source_type,
        "fsx_pvc_name": fsx_pvc_name,
        "fsx_mount_path": fsx_mount_path,
        "s3": s3,
        "launch_script": launch_script,
        "node_count": node_count,
        "replicas": replicas,
        "instance_type": instance_type,
        "gpu_per_worker": gpu_per_worker,
        "cpu_request_millicores": cpu_request_millicores,
        "cpu_limit_millicores": cpu_limit_millicores,
        "memory_request_mib": memory_request_mib,
        "memory_limit_mib": memory_limit_mib,
        "efa_per_worker": efa_per_worker,
        "run_as_root": run_as_root,
        "labels": labels,
        "phase": "initializing",
        "endpoint_url": None,
        "created_at": now,
        "updated_at": now,
    }
    await ri_repo.upsert_resource(
        workspace_id=str(workspace_id),
        resource_type=_tables.RESOURCE_TYPE_DYNAMO,
        resource_id=resource_id,
        creator_user_id=str(creator_user_id),
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_cr_name,
        resource_kind=_RESOURCE_KIND,
        display_name=display_name,
        metadata=_dyn_to_md(dyn),
    )
    return dyn


async def mark_stopped(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """停止: phase=Stopped + 保留 DDB 行 (照 inference)。删 CR 后 grove 回收 pod。"""
    del db
    row["phase"] = "Stopped"
    row["endpoint_url"] = None
    row["kueue_status"] = KUEUE_FINISHED
    row["stop_requested"] = True
    await ri_repo.mark_stopped_inference(
        row["workspace_id"], row["id"], _tables.RESOURCE_TYPE_DYNAMO
    )
    await ri_repo.clear_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_DYNAMO, row["id"]
    )
    return row


async def delete(db: Any, row: dict[str, Any]) -> None:
    del db
    await ri_repo.delete_resource(
        row["workspace_id"], _tables.RESOURCE_TYPE_DYNAMO, row["id"]
    )
