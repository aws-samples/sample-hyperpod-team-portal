"""DevInstance CRUD (DDB-only).

K8s Workspace CR 是 SoT; DDB ResourceIndex 只做按 workspace / creator
反查的索引. 业务字段透过 metadata_json 存在 ResourceIndex item.

签名 (db 参数保留兼容旧调用; 内部不使用):
    get(db, id) → DevInstance | None
    get_by_ws_name(db, ws_id, name) → DevInstance | None
    list_by_workspace(db, ws_id, *, phase, creator_user_id) → list
    create(db, **kwargs) → DevInstance
    update(db, row, **kwargs) → DevInstance
    delete(db, row) → None
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import tables as _tables
from app.repositories import resource_index as ri_repo

# 列表页需要全量数据做前端筛选/统计 (Excel 式列筛选), ri_repo 默认 limit=200 会截断。
# 与 training crud 同口径 (见 training/persistence/crud.py _LIST_LIMIT)。
_LIST_LIMIT = 5000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(_uuid.uuid4())


def _ri_to_dev(item: dict[str, Any]) -> dict[str, Any]:
    """ResourceIndex item → DevInstance dict (合成 phase / 业务字段)."""
    md = dict(item.get("metadata") or {})
    out: dict[str, Any] = {
        "id": item.get("resource_id"),
        "workspace_id": item.get("workspace_id"),
        "creator_user_id": item.get("creator_user_id"),
        "name": md.get("name") or item.get("display_name"),
        "display_name": item.get("display_name"),
        "description": md.get("description"),
        "k8s_namespace": item.get("k8s_namespace"),
        "k8s_workspace_name": item.get("k8s_name"),
        "template_name": md.get("template_name"),
        "app_type": md.get("app_type"),
        "image": md.get("image"),
        "cpu_request_millicores": int(md.get("cpu_request_millicores") or 0),
        "memory_request_mib": int(md.get("memory_request_mib") or 0),
        "gpu_count": int(md.get("gpu_count") or 0),
        "efa_count": int(md.get("efa_count") or 0),
        "storage_size_gib": int(md.get("storage_size_gib") or 0),
        "priority_class": md.get("priority_class"),
        "desired_status": md.get("desired_status") or "Running",
        "phase": md.get("phase") or "Creating",
        "access_url": md.get("access_url"),
        "ssm_managed_id": md.get("ssm_managed_id"),
        "ssm_init_status": md.get("ssm_init_status") or "pending",
        "last_sync_at": md.get("last_sync_at"),
        "last_condition_message": md.get("last_condition_message"),
        "status_detail": md.get("status_detail"),
        "kueue_status": md.get("kueue_status"),
        "env_json": md.get("env_json") or {},
        "metadata_json": md.get("metadata_json") or {},
        "created_at": item.get("created_at"),
        "started_at": md.get("started_at"),
        "stopped_at": md.get("stopped_at"),
        "deleted_at": item.get("deleted_at"),
        "updated_at": md.get("updated_at") or item.get("created_at"),
    }
    return out


def _dev_to_md(dev: dict[str, Any]) -> dict[str, Any]:
    """DevInstance dict → ResourceIndex.metadata payload (业务字段)."""
    return {
        k: v
        for k, v in {
            "name": dev.get("name"),
            "description": dev.get("description"),
            "template_name": dev.get("template_name"),
            "app_type": dev.get("app_type"),
            "image": dev.get("image"),
            "cpu_request_millicores": dev.get("cpu_request_millicores"),
            "memory_request_mib": dev.get("memory_request_mib"),
            "gpu_count": dev.get("gpu_count"),
            "efa_count": dev.get("efa_count"),
            "storage_size_gib": dev.get("storage_size_gib"),
            "priority_class": dev.get("priority_class"),
            "desired_status": dev.get("desired_status"),
            "phase": dev.get("phase"),
            "access_url": dev.get("access_url"),
            "ssm_managed_id": dev.get("ssm_managed_id"),
            "ssm_init_status": dev.get("ssm_init_status"),
            "last_sync_at": dev.get("last_sync_at"),
            "last_condition_message": dev.get("last_condition_message"),
            "env_json": dev.get("env_json") or {},
            "metadata_json": dev.get("metadata_json") or {},
            "started_at": dev.get("started_at"),
            "stopped_at": dev.get("stopped_at"),
            "updated_at": dev.get("updated_at"),
        }.items()
        if v is not None
    }


async def _find_by_id(resource_id: str) -> dict[str, Any] | None:
    """按业务 resource_id 精确取单行 (走 resource_id-index GSI, O(1))。

    替代旧 list_by_type 全类型分区扫 + 内存轮询。校验 resource_type 防御性
    确保命中的确是 dev 行 (原 list_by_type 隐含只在本类型找, 保持等价语义)。
    """
    it = await ri_repo.get_by_resource_id(resource_id)
    if it and it.get("resource_type") == _tables.RESOURCE_TYPE_DEV:
        return it
    return None


async def get(db: Any, id_: Any) -> dict[str, Any] | None:
    del db
    item = await _find_by_id(str(id_))
    return _ri_to_dev(item) if item else None


async def get_by_ws_name(
    db: Any, ws_id: Any, name: str
) -> dict[str, Any] | None:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_DEV, limit=_LIST_LIMIT
    )
    for it in items:
        md = it.get("metadata") or {}
        if md.get("name") == name or it.get("display_name") == name:
            return _ri_to_dev(it)
    return None


async def list_by_workspace(
    db: Any,
    ws_id: Any,
    phase: str | None = None,
    creator_user_id: Any | None = None,
) -> list[dict[str, Any]]:
    del db
    items = await ri_repo.list_by_workspace(
        str(ws_id), resource_type=_tables.RESOURCE_TYPE_DEV, limit=_LIST_LIMIT
    )
    # scope=mine (creator_user_id 非 None): 结果 = 我创建的 ∪ 分享给我的。
    # scope=all (None): 不过滤 creator, 沿用原行为。
    shared_ids: set[str] = set()
    if creator_user_id is not None:
        from app.modules.sharing import visibility
        shared_ids = await visibility.shared_res_ids(
            str(ws_id), str(creator_user_id), _tables.RESOURCE_TYPE_DEV
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
        out.append(_ri_to_dev(it))
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
    k8s_workspace_name: str,
    template_name: str,
    app_type: str,
    image: str,
    cpu_request_millicores: int,
    memory_request_mib: int,
    gpu_count: int,
    efa_count: int = 0,
    storage_size_gib: int,
    env_json: dict[str, Any],
    priority_class: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del db
    resource_id = _new_id()
    now = _now_iso()
    dev: dict[str, Any] = {
        "id": resource_id,
        "workspace_id": str(workspace_id),
        "creator_user_id": str(creator_user_id),
        "name": name,
        "display_name": display_name,
        "description": description,
        "k8s_namespace": k8s_namespace,
        "k8s_workspace_name": k8s_workspace_name,
        "template_name": template_name,
        "app_type": app_type,
        "image": image,
        "cpu_request_millicores": cpu_request_millicores,
        "memory_request_mib": memory_request_mib,
        "gpu_count": gpu_count,
        "efa_count": efa_count,
        "storage_size_gib": storage_size_gib,
        "priority_class": priority_class,
        "desired_status": "Running",
        "phase": "Creating",
        "env_json": env_json,
        "metadata_json": metadata_json or {},
        "created_at": now,
        "updated_at": now,
    }
    await ri_repo.upsert_resource(
        workspace_id=str(workspace_id),
        resource_type=_tables.RESOURCE_TYPE_DEV,
        resource_id=resource_id,
        creator_user_id=str(creator_user_id),
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_workspace_name,
        resource_kind="Workspace",
        display_name=display_name,
        metadata=_dev_to_md(dev),
    )
    return dev


# platform-api update 写的业务字段白名单 (= _dev_to_md 的字段去掉 informer 拥有的
# 动态状态字段)。显式列举而非"全集减状态集": repo._build_business_update_expr 会拒绝
# repo._STATUS_FIELDS (phase/started_at/ended_at/last_condition_message/priority_class/
# k8s_resource_version), 显式白名单可避免误传触发 ValueError, 也让"谁写哪些字段"一目了然。
# 排除项 (归 informer): phase/started_at/last_condition_message · priority_class
# (阶段B 管理员改优先级走 informer 同步) · kueue_status (informer 写的三态状态字段,
# 已移入 repo._STATUS_FIELDS)。
# access_url 在白名单: 它是 sync_from_k8s 从 CR status.accessURL 拉的派生值, informer
# 暂不写, 由 detail/access 端点的 sync 落库 (不加进白名单则部分更新永不落库 → list 空)。
_DEV_BUSINESS_FIELDS = (
    "name",
    "description",
    "template_name",
    "app_type",
    "image",
    "cpu_request_millicores",
    "memory_request_mib",
    "gpu_count",
    "efa_count",
    "storage_size_gib",
    "desired_status",
    "access_url",
    "ssm_managed_id",
    "ssm_init_status",
    "last_sync_at",
    "env_json",
    "metadata_json",
    "stopped_at",
    "updated_at",
)


async def update(
    db: Any,
    row: dict[str, Any],
    *,
    display_name: str | None = None,
    description: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """部分更新开发机的业务字段 (A4 bugfix: 不再整行 PutItem)。

    为什么改: 开发机接入 informer 后, DDB 有两个写入方 — informer 部分更新状态字段
    (phase/started_at/...), platform-api (stop/start/改名/SSM) 写业务字段。原实现用
    upsert_resource 整行 PutItem 覆盖整个 metadata, 会把 informer 刚写的 phase 用 row
    里的旧值覆盖、并把 k8s_resource_version 冲成 null (真集群实证: 停止开发机后 DDB
    phase 仍 Running)。改为部分更新 (update_business_fields → UpdateItem SET
    metadata.<业务子字段>), 只写业务字段, 与 informer 写不同子字段, 互不覆盖。
    """
    del db
    if display_name is not None:
        row["display_name"] = display_name
    if description is not None:
        row["description"] = description
    if env is not None:
        row["env_json"] = env
    row["updated_at"] = _now_iso()
    # 业务字段直接从 row 取 (保留 None — None 会被 update_business_fields 转成 REMOVE
    # 子字段, 实现清空, 如 stop 时 ssm_managed_id=None)。剔除 informer 拥有的状态字段。
    # 不用 _dev_to_md: 它 `if v is not None` 过滤 None, 部分更新下会导致清空失效。
    business = {
        k: row.get(k)
        for k in _DEV_BUSINESS_FIELDS
        if k in row  # 只更新 row 里实际带的字段
    }
    await ri_repo.update_business_fields(
        workspace_id=row["workspace_id"],
        resource_type=_tables.RESOURCE_TYPE_DEV,
        resource_id=row["id"],
        fields=business,
    )
    return row


async def delete(db: Any, row: dict[str, Any]) -> None:
    del db
    await ri_repo.delete_resource(
        row["workspace_id"], _tables.RESOURCE_TYPE_DEV, row["id"]
    )
