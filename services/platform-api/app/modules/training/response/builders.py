"""TrainingJob 响应视图构建 (DDB-only)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.pod_status import summarize_pod
from app.modules.training.api.schemas import (
    TrainingJobDetail,
    TrainingJobListItem,
)


def _denumerize(v: Any) -> Any:
    """递归把 DynamoDB 的 Decimal 规整成 int/float (含 dict/list 嵌套)。

    用于 run_policy_override 这类 `dict[str, Any]` 自由字段: 其内的 Decimal 若直接交给
    pydantic v2 序列化, mode='json' 会转成字符串 ('-1'), 前端克隆 yaml.dump 再带引号,
    最终撞后端 _require_int 校验 500 (字符串自我繁殖)。这里在出口规整为真正的数字,
    从源头断掉字符串化。整数 Decimal → int, 非整数 → float。
    """
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _denumerize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_denumerize(x) for x in v]
    return v


def _compat_code(code: Any) -> Any:
    """ 向后兼容: 旧 github 代码源 (source=github) 已废弃, CodeSource 收窄只 fsx。
    存量任务 md.code 若是 github → 降级 None (否则 pydantic 校验挂 500)。
    """
    if isinstance(code, dict) and code.get("source") == "github":
        return None
    return code


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
        "node_name": (p.get("spec") or {}).get("node_name"),
        "pod_ip": status_.get("pod_ip"),
        "host_ip": status_.get("host_ip"),
        "start_time": status_.get("start_time"),
    }


async def build_list_item(
    db: Any, row: dict[str, Any]
) -> TrainingJobListItem:
    """组 training job 列表项.

    PR feat/no-users-table-username-as-id, 2026-05-20:
        - 不再调 user_crud.get_user 反查 (Users 表删了)
        - creator_display_name 直接读 row 的冗余字段 (orchestration 写入时拍快照)
        - PR 5 真接通 ResourceIndex 写入流程时, 写入端要塞 creator_email/display_name
    """
    del db
    # main 已废 DDB Users 表, creator_display_name 改读 row 冗余字段
    # (orchestration 写入时拍快照, 详见 PR feat/no-users-table).
    # 不再查 workspace: 列表项/详情都不用 workspace_display_name (列表页自己维护 ws 名),
    # 省掉每行一次 GetItem。
    return TrainingJobListItem(
        id=str(row.get("id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        creator_user_id=str(row.get("creator_user_id") or ""),
        creator_display_name=row.get("creator_display_name") or row.get("creator_user_id") or "",
        name=row.get("name") or "",
        display_name=row.get("display_name") or "",
        phase=row.get("phase") or "Pending",
        kueue_status=row.get("kueue_status"),
        node_count=int(row.get("node_count") or 1),
        gpu_per_node=int(row.get("gpu_per_node") or 0),
        efa_per_node=int(row.get("efa_per_node") or 0),
        cpu_per_node_millicores=int(row.get("cpu_per_node_millicores") or 0),
        memory_per_node_mib=int(row.get("memory_per_node_mib") or 0),
        created_at=row.get("created_at") or "",
        started_at=row.get("started_at"),
        ended_at=row.get("ended_at"),
        last_sync_at=row.get("last_sync_at"),
    )


async def build_detail(
    db: Any,
    row: dict[str, Any],
    conditions: list[dict[str, Any]] | None = None,
    pods: list[dict[str, Any]] | None = None,
) -> TrainingJobDetail:
    del db
    base = await build_list_item(None, row)
    md = row.get("metadata_json") or {}
    rp = md.get("run_policy") or {}
    return TrainingJobDetail(
        **base.model_dump(),
        description=row.get("description"),
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_job_name=row.get("k8s_job_name") or "",
        image=row.get("image") or "",
        command=row.get("command") or "",
        last_condition_message=row.get("last_condition_message"),
        env=row.get("env_json") or {},
        clean_pod_policy=rp.get("clean_pod_policy", "All"),
        ttl_seconds_after_finished=rp.get("ttl_seconds_after_finished", -1),
        active_deadline_seconds=rp.get("active_deadline_seconds"),
        job_max_retry_count=rp.get("job_max_retry_count", 0),
        # 用户编辑的 runPolicy 裸 YAML 整段 (克隆回填原文; None=用 4 字段重建)
        # _denumerize: 规整内部 Decimal → int/float, 防 pydantic 序列化成字符串 (见上)
        run_policy_override=_denumerize(md.get("run_policy_override")),
        # 训练参数 — md 直读 (旧 github code 降级, 向后兼容)
        code=_compat_code(md.get("code")),
        env_secrets=md.get("env_secrets") or [],
        fsx_pvc=md.get("fsx_pvc"),
        fsx_mount_path=md.get("fsx_mount_path"),
        fsx_gid=md.get("fsx_gid"),
        s3_datasets=md.get("s3_datasets") or [],
        extra_fsx_mounts=md.get("extra_fsx_mounts") or [],
        instance_type=md.get("instance_type"),  # 选的机型, 克隆回填用
        experiment_id=md.get("experiment_id"),
        priority_class=md.get("priority_class"),
        spares=md.get("spares"),
        topology_mode=md.get("topology_mode"),
        topology_label=md.get("topology_label"),
        labels=md.get("labels") or {},
        conditions=conditions or [],
        pods=[_pod_summary(p) for p in (pods or [])],
    )
