"""TrainingJob CRUD (DDB-only).

K8s CR 是 SoT; DDB ResourceIndex 写索引.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import tables as _tables
from app.modules.shared.kueue_status import KUEUE_FINISHED
from app.repositories import resource_index as ri_repo

# 列表页需要全量数据做前端筛选/统计 (Excel 式列筛选), ri_repo 默认 limit=200 会截断。
# 训练任务量级可能比 dev/inference 大 (含历史终态), 单独放宽; 仍设上限防极端 ws 拖垮请求。
_LIST_LIMIT = 5000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _ri_to_job(item: dict[str, Any]) -> dict[str, Any]:
    md = dict(item.get("metadata") or {})
    return {
        "id": item.get("resource_id"),
        "workspace_id": item.get("workspace_id"),
        "creator_user_id": item.get("creator_user_id"),
        "name": md.get("name") or item.get("display_name"),
        "display_name": item.get("display_name"),
        "description": md.get("description"),
        "k8s_namespace": item.get("k8s_namespace"),
        "k8s_job_name": item.get("k8s_name"),
        "image": md.get("image"),
        "command": md.get("command"),
        "node_count": int(md.get("node_count") or 1),
        "gpu_per_node": int(md.get("gpu_per_node") or 0),
        "efa_per_node": int(md.get("efa_per_node") or 0),
        "cpu_per_node_millicores": int(md.get("cpu_per_node_millicores") or 0),
        "memory_per_node_mib": int(md.get("memory_per_node_mib") or 0),
        "phase": md.get("phase") or "Pending",
        "kueue_status": md.get("kueue_status"),
        "last_condition_message": md.get("last_condition_message"),
        "last_sync_at": md.get("last_sync_at"),
        "env_json": md.get("env_json") or {},
        "metadata_json": md.get("metadata_json") or {},
        "created_at": item.get("created_at"),
        "started_at": md.get("started_at"),
        "ended_at": md.get("ended_at"),
        "status_detail": md.get("status_detail"),
        "log_streams": md.get("log_streams"),
        "updated_at": md.get("updated_at") or item.get("created_at"),
    }


def _job_to_md(job: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "name": job.get("name"),
            "description": job.get("description"),
            "image": job.get("image"),
            "command": job.get("command"),
            "node_count": job.get("node_count"),
            "gpu_per_node": job.get("gpu_per_node"),
            "efa_per_node": job.get("efa_per_node"),
            "cpu_per_node_millicores": job.get("cpu_per_node_millicores"),
            "memory_per_node_mib": job.get("memory_per_node_mib"),
            "phase": job.get("phase"),
            "last_condition_message": job.get("last_condition_message"),
            # status_detail (debug 弹窗用): 与 _ri_to_job 读出对称; 缺它则业务 update
            # 整行 PutItem 会把 informer 写的 status_detail 冲掉。
            "status_detail": job.get("status_detail"),
            # log_streams (任务 finished 后缓存的 CloudWatch stream 列表): 与
            # _ri_to_job 读出对称, 否则业务 update 整行 PutItem 会把缓存抹掉。
            "log_streams": job.get("log_streams"),
            "last_sync_at": job.get("last_sync_at"),
            "env_json": job.get("env_json") or {},
            "metadata_json": job.get("metadata_json") or {},
            "started_at": job.get("started_at"),
            "ended_at": job.get("ended_at"),
            "updated_at": job.get("updated_at"),
        }.items()
        if v is not None
    }


async def _find_by_id(resource_id: str) -> dict[str, Any] | None:
    # 精确走 resource_id-index GSI (O(1)), 替代 list_by_type 全类型分区扫。
    # 校验 resource_type: id 全局唯一, 但防御性确保命中的确是 train 行 (原
    # list_by_type 隐含只在本类型找, 保持等价语义)。
    it = await ri_repo.get_by_resource_id(resource_id)
    if it and it.get("resource_type") == _tables.RESOURCE_TYPE_TRAIN:
        return it
    return None


async def get(db: Any, id_: Any) -> dict[str, Any] | None:
    del db
    item = await _find_by_id(str(id_))
    return _ri_to_job(item) if item else None


async def get_by_ws_name(
    db: Any, ws_id: Any, name: str
) -> dict[str, Any] | None:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_TRAIN, limit=_LIST_LIMIT
    )
    for it in items:
        md = it.get("metadata") or {}
        if md.get("name") == name or it.get("display_name") == name:
            return _ri_to_job(it)
    return None


async def list_by_workspace(
    db: Any,
    ws_id: Any,
    phase: str | None = None,
    creator_user_id: Any | None = None,
) -> list[dict[str, Any]]:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_TRAIN, limit=_LIST_LIMIT
    )
    # scope=mine (creator_user_id 非 None): 结果 = 我创建的 ∪ 分享给我的。
    # scope=all (None): 不过滤 creator, 沿用原行为。
    shared_ids: set[str] = set()
    if creator_user_id is not None:
        from app.modules.sharing import visibility
        shared_ids = await visibility.shared_res_ids(
            str(ws_id), str(creator_user_id), _tables.RESOURCE_TYPE_TRAIN
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
        out.append(_ri_to_job(it))
    return out


async def create(
    db: Any,
    *,
    workspace_id: Any,
    creator_user_id: Any,
    name: str,
    display_name: str,
    description: str | None,
    k8s_namespace: str,
    k8s_job_name: str,
    image: str,
    command: str | list[str],
    node_count: int,
    gpu_per_node: int,
    cpu_per_node_millicores: int,
    memory_per_node_mib: int,
    efa_per_node: int = 0,
    env_json: dict[str, Any],
    metadata_json: dict[str, Any] | None = None,
    resource_id: str | None = None,
) -> dict[str, Any]:
    del db
    # resource_id 由 caller 传 (= CR label training-job-id, informer 靠它关联同一行).
    # 不传则自动生成 (向后兼容老调用).
    resource_id = resource_id or _new_id()
    now = _now_iso()
    job = {
        "id": resource_id,
        "workspace_id": str(workspace_id),
        "creator_user_id": str(creator_user_id),
        "name": name,
        "display_name": display_name,
        "description": description,
        "k8s_namespace": k8s_namespace,
        "k8s_job_name": k8s_job_name,
        "image": image,
        "command": command,
        "node_count": node_count,
        "gpu_per_node": gpu_per_node,
        "efa_per_node": efa_per_node,
        "cpu_per_node_millicores": cpu_per_node_millicores,
        "memory_per_node_mib": memory_per_node_mib,
        "phase": "Pending",
        "env_json": env_json,
        "metadata_json": metadata_json or {},
        "created_at": now,
        "updated_at": now,
    }
    await ri_repo.upsert_resource(
        workspace_id=str(workspace_id),
        resource_type=_tables.RESOURCE_TYPE_TRAIN,
        resource_id=resource_id,
        creator_user_id=str(creator_user_id),
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_job_name,
        resource_kind="HyperPodPyTorchJob",
        display_name=display_name,
        metadata=_job_to_md(job),
    )
    return job


async def delete(db: Any, row: dict[str, Any]) -> None:
    del db
    await ri_repo.delete_resource(
        row["workspace_id"], _tables.RESOURCE_TYPE_TRAIN, row["id"]
    )


async def mark_stopped(db: Any, row: dict[str, Any]) -> dict[str, Any]:
    """停止: phase=Stopped + kueue_status=Finished + stop_requested, 保留 DDB 行与 spec。
    不打 deleted_at (列表保留); stop_requested 哨兵让 informer 收 DELETED 时跳过软删。
    """
    del db
    ended = _now_iso()  # 停止即结束, ended_at = 停止时刻 (否则前端用当前时间, 时长一直涨)
    row["phase"] = "Stopped"
    row["kueue_status"] = KUEUE_FINISHED
    row["stop_requested"] = True
    row["ended_at"] = ended
    await ri_repo.mark_stopped_training(row["workspace_id"], row["id"], ended_at=ended)
    # 清残留 deleted_at (并发 sync 可能抢先打软删标), 确保 Stopped 行列表保留
    await ri_repo.clear_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_TRAIN, row["id"]
    )
    return row
