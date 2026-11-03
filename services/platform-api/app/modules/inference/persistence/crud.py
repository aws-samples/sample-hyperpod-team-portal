"""Inference CRUD (DDB-only).

K8s CR 是 SoT; DDB ResourceIndex 写索引.
镜像 training/persistence/crud.py 模式, resource_type='inference'.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import tables as _tables
from app.core.priority_defaults import default_priority_class
from app.modules.shared.kueue_status import KUEUE_FINISHED
from app.repositories import resource_index as ri_repo

_RESOURCE_KIND = "InferenceEndpointConfig"

# 列表页需要全量数据做前端筛选/统计 (Excel 式列筛选), ri_repo 默认 limit=200 会截断。
# 与 training crud 同口径 (见 training/persistence/crud.py _LIST_LIMIT)。
_LIST_LIMIT = 5000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _ri_to_inf(item: dict[str, Any]) -> dict[str, Any]:
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
        "k8s_endpoint_name": item.get("k8s_name"),
        # 引擎 / 模型
        "framework": md.get("framework") or "sglang",
        "model_name": md.get("model_name"),
        "model_mount_path": md.get("model_mount_path") or "/opt/ml/model",
        "model_source_type": md.get("model_source_type"),
        "fsx": md.get("fsx"),
        "s3": md.get("s3"),
        "huggingface": md.get("huggingface"),
        # SGLang
        "image": md.get("image"),
        "invocation_endpoint": md.get("invocation_endpoint"),
        "container_port": int(md.get("container_port") or 8000),
        "sglang_extra_args": md.get("sglang_extra_args") or [],
        "launch_script": md.get("launch_script"),
        # 资源
        "instance_type": md.get("instance_type"),
        "gpu_per_replica": int(md.get("gpu_per_replica") or 1),
        "cpu_request_millicores": int(md.get("cpu_request_millicores") or 0),
        "cpu_limit_millicores": int(md.get("cpu_limit_millicores") or 0),
        "memory_request_mib": int(md.get("memory_request_mib") or 0),
        "memory_limit_mib": int(md.get("memory_limit_mib") or 0),
        "replicas": int(md.get("replicas") or 1),
        # 高级
        "routing_strategy": md.get("routing_strategy") or "roundrobin",
        "l2_kv_cache": md.get("l2_kv_cache") or {"enabled": False},
        "metrics_enabled": bool(md.get("metrics_enabled", True)),
        "public_endpoint": bool(md.get("public_endpoint", False)),
        "labels": md.get("labels") or {},
        "alb_dns": md.get("alb_dns"),
        "env": md.get("env") or {},
        # 状态
        "phase": md.get("phase") or "Pending",
        "priority_class": md.get("priority_class"),
        # kueue_status 三态由 informer 写; 整行 put 必须读出再写回, 否则冲丢 informer 值。
        "kueue_status": md.get("kueue_status"),
        "stop_requested": md.get("stop_requested"),
        "endpoint_url": md.get("endpoint_url"),
        "last_condition_message": md.get("last_condition_message"),
        "status_detail": md.get("status_detail"),
        "last_sync_at": md.get("last_sync_at"),
        "log_streams": md.get("log_streams"),
        # 与 update 写回对称, 否则整行 put 会抹掉
        "ended_at": md.get("ended_at"),
        "created_at": item.get("created_at"),
        "updated_at": md.get("updated_at") or item.get("created_at"),
    }


def _inf_to_md(inf: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "name": inf.get("name"),
            "description": inf.get("description"),
            "framework": inf.get("framework"),
            "model_name": inf.get("model_name"),
            "model_mount_path": inf.get("model_mount_path"),
            "model_source_type": inf.get("model_source_type"),
            "fsx": inf.get("fsx"),
            "s3": inf.get("s3"),
            "huggingface": inf.get("huggingface"),
            "image": inf.get("image"),
            "invocation_endpoint": inf.get("invocation_endpoint"),
            "container_port": inf.get("container_port"),
            "sglang_extra_args": inf.get("sglang_extra_args") or [],
            "launch_script": inf.get("launch_script"),
            "instance_type": inf.get("instance_type"),
            "gpu_per_replica": inf.get("gpu_per_replica"),
            "cpu_request_millicores": inf.get("cpu_request_millicores"),
            "cpu_limit_millicores": inf.get("cpu_limit_millicores"),
            "memory_request_mib": inf.get("memory_request_mib"),
            "memory_limit_mib": inf.get("memory_limit_mib"),
            "replicas": inf.get("replicas"),
            "routing_strategy": inf.get("routing_strategy"),
            "l2_kv_cache": inf.get("l2_kv_cache"),
            "metrics_enabled": inf.get("metrics_enabled"),
            "public_endpoint": inf.get("public_endpoint"),
            "labels": inf.get("labels") or {},
            "alb_dns": inf.get("alb_dns"),
            "env": inf.get("env") or {},
            "phase": inf.get("phase"),
            # priority_class: informer 从 CR label 派生维护, create 写初值 (worker 空窗也有值)。
            "priority_class": inf.get("priority_class"),
            # kueue_status 三态 (informer 写): 与 _ri_to_inf 读出对称, 整行 put 不丢。
            "kueue_status": inf.get("kueue_status"),
            # 用户主动停止哨兵 (informer 不碰此字段, partial UpdateItem 不会冲掉)。
            # _mark_deleted 据此区分"停止删CR"(保留行) vs "删除删CR"(软删)。
            "stop_requested": inf.get("stop_requested"),
            "endpoint_url": inf.get("endpoint_url"),
            "last_condition_message": inf.get("last_condition_message"),
            # status_detail (debug 弹窗用): sync 算出后必须写进 metadata, 否则整行
            # PutItem 丢失它 → DDB 永远没有 (与 _ri_to_inf 读出对称, 缺它则只读不写)。
            "status_detail": inf.get("status_detail"),
            "last_sync_at": inf.get("last_sync_at"),
            # log_streams (任务 finished 后缓存的 CloudWatch stream 列表): 与
            # _ri_to_inf 读出对称, 否则业务 update 整行 PutItem 会把缓存抹掉。
            "log_streams": inf.get("log_streams"),
            # 与 _ri_to_inf 读出对称
            "ended_at": inf.get("ended_at"),
            "creator_display_name": inf.get("creator_display_name"),
            "updated_at": inf.get("updated_at"),
        }.items()
        if v is not None
    }


async def _find_by_id(resource_id: str) -> dict[str, Any] | None:
    # 精确走 resource_id-index GSI (O(1)), 替代 list_by_type 全类型分区扫。
    # 校验 resource_type: id 全局唯一, 但防御性确保命中的确是 inference 行 (原
    # list_by_type 隐含只在本类型找, 保持等价语义)。
    it = await ri_repo.get_by_resource_id(resource_id)
    if it and it.get("resource_type") == _tables.RESOURCE_TYPE_INFERENCE:
        return it
    return None


async def get(db: Any, id_: Any) -> dict[str, Any] | None:
    del db
    item = await _find_by_id(str(id_))
    return _ri_to_inf(item) if item else None


async def get_by_ws_name(
    db: Any, ws_id: Any, name: str
) -> dict[str, Any] | None:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_INFERENCE, limit=_LIST_LIMIT
    )
    for it in items:
        md = it.get("metadata") or {}
        if md.get("name") == name or it.get("display_name") == name:
            return _ri_to_inf(it)
    return None


async def list_by_workspace(
    db: Any,
    ws_id: Any,
    phase: str | None = None,
    creator_user_id: Any | None = None,
) -> list[dict[str, Any]]:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_INFERENCE, limit=_LIST_LIMIT
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
        out.append(_ri_to_inf(it))
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
    k8s_endpoint_name: str,
    framework: str,
    model_name: str,
    model_mount_path: str,
    model_source_type: str,
    fsx: dict[str, Any] | None,
    s3: dict[str, Any] | None,
    huggingface: dict[str, Any] | None,
    image: str,
    invocation_endpoint: str,
    container_port: int,
    sglang_extra_args: list[str],
    launch_script: str | None = None,
    instance_type: str,
    gpu_per_replica: int,
    cpu_request_millicores: int,
    cpu_limit_millicores: int,
    memory_request_mib: int,
    memory_limit_mib: int,
    replicas: int,
    routing_strategy: str,
    l2_kv_cache: dict[str, Any],
    metrics_enabled: bool,
    public_endpoint: bool,
    labels: dict[str, str],
    env: dict[str, str],
) -> dict[str, Any]:
    del db
    resource_id = _new_id()
    now = _now_iso()
    inf = {
        "id": resource_id,
        "workspace_id": str(workspace_id),
        "creator_user_id": str(creator_user_id),
        "creator_display_name": creator_display_name or str(creator_user_id),
        "name": name,
        "display_name": display_name,
        "description": description,
        "k8s_namespace": k8s_namespace,
        "k8s_endpoint_name": k8s_endpoint_name,
        "framework": framework,
        "model_name": model_name,
        "model_mount_path": model_mount_path,
        "model_source_type": model_source_type,
        "fsx": fsx,
        "s3": s3,
        "huggingface": huggingface,
        "image": image,
        "invocation_endpoint": invocation_endpoint,
        "container_port": container_port,
        "sglang_extra_args": sglang_extra_args,
        "launch_script": launch_script,
        "instance_type": instance_type,
        "gpu_per_replica": gpu_per_replica,
        "cpu_request_millicores": cpu_request_millicores,
        "cpu_limit_millicores": cpu_limit_millicores,
        "memory_request_mib": memory_request_mib,
        "memory_limit_mib": memory_limit_mib,
        "replicas": replicas,
        "routing_strategy": routing_strategy,
        "l2_kv_cache": l2_kv_cache,
        "metrics_enabled": metrics_enabled,
        "public_endpoint": public_endpoint,
        "labels": labels,
        "env": env,
        "phase": "Pending",
        # 推理统一默认档 (cr.py 同值); informer 后续从 CR label 刷新。
        "priority_class": default_priority_class("inference"),
        "endpoint_url": None,
        "created_at": now,
        "updated_at": now,
    }
    await ri_repo.upsert_resource(
        workspace_id=str(workspace_id),
        resource_type=_tables.RESOURCE_TYPE_INFERENCE,
        resource_id=resource_id,
        creator_user_id=str(creator_user_id),
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_endpoint_name,
        resource_kind=_RESOURCE_KIND,
        display_name=display_name,
        metadata=_inf_to_md(inf),
    )
    return inf


async def update(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Sync 回写: 部分更新 sync 独占的业务字段。

    只写 endpoint_url + alb_dns + last_sync_at + updated_at。phase/status_detail/
    last_condition_message/kueue_status/active_ws 归 informer (update_status_if_changed),
    sync 不再碰 — 改前整行 PutItem 会把它们冲掉 (active_ws/status_detail 被抹 bug 根源)。
    endpoint_url 不在 _STATUS_FIELDS, 安全闸放行; 与 informer 同源同值, 竞态无害。
    None 值 → update_business_fields 转 REMOVE (与原整行 put 过滤 None 效果一致)。
    """
    del db
    row["updated_at"] = _now_iso()
    await ri_repo.update_business_fields(
        workspace_id=row["workspace_id"],
        resource_type=_tables.RESOURCE_TYPE_INFERENCE,
        resource_id=row["id"],
        fields={
            "endpoint_url": row.get("endpoint_url"),
            "alb_dns": row.get("alb_dns"),
            "last_sync_at": row.get("last_sync_at"),
            "updated_at": row["updated_at"],
        },
    )
    return row


async def mark_stopped(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """停止: phase=Stopped + endpoint_url 清空, 保留 DDB 行与全部 spec (支持停止后克隆重建)。

    一次部分更新: SET 4 字段 + REMOVE active_ws, 不再整行 put。
    不打 deleted_at (否则列表过滤掉); spec/log 字段原样留 (克隆 + 日志查用)。
    """
    del db
    ended = _now_iso()  # 停止即结束, 否则前端按当前时间算, 时长一直涨
    row["phase"] = "Stopped"
    row["endpoint_url"] = None
    row["ended_at"] = ended
    # 停止即终态; 删 CR 后 informer 收 DELETED 跳过+不再 reconcile, 显式置 Finished
    # 否则 kueue_status 卡运行态 → 总览误显活跃+误计 running。
    row["kueue_status"] = KUEUE_FINISHED
    # 哨兵: phase 会被 informer reconcile 冲回 CR 派生值 (Running 等), 但 stop_requested
    # informer 永不写, 故存活。删 CR 后 informer 收 DELETED 据此跳过软删 (保留行可查日志)。
    row["stop_requested"] = True
    # 部分更新 (取代整行 put): SET 4 停止字段 + REMOVE 顶层 active_ws (出稀疏 GSI)。
    await ri_repo.mark_stopped_inference(
        row["workspace_id"], row["id"], ended_at=ended
    )
    # 清残留 deleted_at (并发 sync 可能抢先打软删标), 确保 Stopped 行列表保留
    await ri_repo.clear_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_INFERENCE, row["id"]
    )
    return row


async def delete(db: Any, row: dict[str, Any]) -> None:
    del db
    await ri_repo.delete_resource(
        row["workspace_id"], _tables.RESOURCE_TYPE_INFERENCE, row["id"]
    )
