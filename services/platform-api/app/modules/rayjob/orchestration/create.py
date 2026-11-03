"""RayJob 创建编排 · 照 dynamo create_dynamo_flow。

授权反查 (机型配额 / FSx / env secret) 不信前端 (API 公网防越权)。
create 与 preview 共用 _render_cr → 预览即真相。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import t
from app.core.labels import validate_user_labels
from app.core.logging import get_logger
from app.core.naming import RAYJOB_NAME_MAX, make_dns_name, sanitize_dns_label
from app.modules.rayjob.api.schemas import RayJobCreate
from app.modules.rayjob.domain.cr import render_rayjob_cr
from app.modules.rayjob.persistence import crud
from app.modules.workspace import crud as ws_crud
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

_FALLBACK_K8S_NS = "default"


async def _assert_instance_type_allowed(hp: Any, ws_id: Any, instance_type: str) -> None:
    """机型必须在 ws ComputeQuota 已分配机型内 (API 公网防越权; 同 dynamo)。"""
    from app.modules.quota.orchestration.workspace_quota import get_workspace_quota

    quota = await get_workspace_quota(None, hp, ws_id)
    allowed = {r.instance_type for r in (quota.resources or [])}
    if instance_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t(
                "rayjob.instance_type_not_allowed",
                instance_type=instance_type,
                allowed=sorted(allowed) or t("rayjob.allowed_none"),
            ),
        )


async def _resolve_fsx_mounts(
    ws_id: Any, username: str, payload: RayJobCreate
) -> list[dict[str, Any]]:
    """按 payload.fsx_mounts 的 pvc_name 反查该 user 被授权的 FSx, 返真值 dict 列表 (照训练)。

    安全: 只接受该 user 在该 ws 被授权的 FSx; 不在授权列表 → 403。
    mount_path/read_only(access)/gid 取授权真值, 不信前端。
    """
    refs = payload.fsx_mounts or []
    if not refs:
        return []
    from app.modules.devinstance.orchestration.pvcs import list_permitted_mounts

    permitted = await list_permitted_mounts(str(ws_id), username)
    by_pvc = {p.name: p for p in permitted}
    resolved: list[dict[str, Any]] = []
    for ref in refs:
        p = by_pvc.get(ref.pvc_name)
        if p is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                t("rayjob.fsx_not_authorized", pvc_name=ref.pvc_name),
            )
        resolved.append({
            "pvc_name": p.name,
            "mount_path": p.mount_path or "",
            "read_only": (p.access == "ro"),
            "gid": p.gid,
        })
    return resolved


async def _resolve_s3_datasets(
    ws_id: Any, payload: RayJobCreate
) -> list[dict[str, Any]]:
    """按 payload.s3_datasets 的 mount_id 反查 ws 已挂 S3, 返真值 dict 列表 (照训练)。

    安全: 只接受 ws 已挂载/授权的 S3; mount_id 不在列表 → 403。真值取 ws 挂载。
    """
    refs = payload.s3_datasets or []
    if not refs:
        return []
    from app.modules.workspace.orchestration.s3 import list_workspace_s3_flow

    mounts = await list_workspace_s3_flow(str(ws_id))
    by_id = {m.get("mount_id"): m for m in mounts}
    resolved: list[dict[str, Any]] = []
    for ref in refs:
        m = by_id.get(ref.mount_id)
        if m is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                t("rayjob.s3_mount_not_allowed", mount_id=ref.mount_id),
            )
        resolved.append({
            "bucket": m.get("bucket_name") or "",
            "prefix": m.get("prefix") or "",
            "mount_path": m.get("mount_path") or "",
            "pvc_name": m.get("pvc_name") or "",
        })
    return resolved


async def _resolve_env_secrets(
    k8s: K8sClient, k8s_ns: str, username: str, payload: RayJobCreate
) -> None:
    """env_secrets: 补 secret_ref = 本人固定 secret 名 + 校验 key 存在。"""
    if not payload.env_secrets:
        return
    own = f"{sanitize_dns_label(username, fallback='user')}-secrets"
    for s in payload.env_secrets:
        s.secret_ref = own
    own_keys = set(await k8s.get_secret_keys(k8s_ns, own))
    missing = {s.secret_key for s in payload.env_secrets} - own_keys
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t("rayjob.secret_keys_missing", keys=", ".join(sorted(missing))),
        )


def _render_cr(
    *,
    payload: RayJobCreate,
    ws_id: str,
    k8s_ns: str,
    name: str,
    rayjob_id: str,
    creator_id: str,
    resolved_fsx: list[dict[str, Any]],
    resolved_s3: list[dict[str, Any]],
) -> dict[str, Any]:
    """组 render_rayjob_cr 入参 → CR dict。create 与 preview 共用 (预览即真相)。"""
    env_secrets = [s.model_dump() for s in payload.env_secrets]
    fsx_gids = sorted({
        int(m["gid"]) for m in resolved_fsx if m.get("gid") is not None
    })
    return render_rayjob_cr(
        name=name,
        namespace=k8s_ns,
        rayjob_id=rayjob_id,
        workspace_id=ws_id,
        creator_id=creator_id,
        extra_fsx_mounts=resolved_fsx,
        s3_datasets=resolved_s3,
        fsx_supplemental_gids=fsx_gids,
        entry_script_path=payload.entry_script_path,
        head_image=payload.head_image,
        worker_image=payload.worker_image,
        worker_replicas=payload.worker_replicas,
        head_instance_type=payload.head_instance_type,
        head_gpu=payload.head_gpu,
        head_cpu_request_millicores=payload.head_cpu_request_millicores,
        head_cpu_limit_millicores=payload.head_cpu_limit_millicores,
        head_memory_request_mib=payload.head_memory_request_mib,
        head_memory_limit_mib=payload.head_memory_limit_mib,
        head_efa=payload.head_efa,
        worker_instance_type=payload.worker_instance_type,
        gpu_per_node=payload.gpu_per_node,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        efa_per_node=payload.efa_per_node,
        max_run_hours=payload.max_run_hours,
        ttl_seconds_after_finished=payload.ttl_seconds_after_finished,
        backoff_limit=payload.backoff_limit,
        env=payload.env or {},
        env_secrets=env_secrets,
        run_as_root=payload.run_as_root,
        user_labels=validate_user_labels(payload.labels),
    )


def _dump_cr_yaml(cr: dict[str, Any]) -> str:
    """CR dict → YAML (含换行 str 走 literal block |; 同 dynamo)。"""
    import yaml as _yaml

    class _BlockDumper(_yaml.SafeDumper):
        pass

    def _str_rep(dumper: _yaml.Dumper, data: str) -> Any:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _BlockDumper.add_representer(str, _str_rep)
    return _yaml.dump(
        cr, Dumper=_BlockDumper, sort_keys=False, default_flow_style=False,
        allow_unicode=True,
    )


async def preview_rayjob_flow(
    hp: Any, ws_id: Any, payload: RayJobCreate, current_user: dict[str, Any]
) -> str:
    """渲最终 CR YAML, 不创建 · 与 create 共用渲染 → 预览即真相。"""
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    await _assert_instance_type_allowed(hp, ws_id, payload.head_instance_type)
    await _assert_instance_type_allowed(hp, ws_id, payload.worker_instance_type)
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    try:
        resolved_fsx = await _resolve_fsx_mounts(ws_id, username, payload)
    except HTTPException:
        resolved_fsx = []  # 预览不因授权失败中断 (真 create 会拦)
    try:
        resolved_s3 = await _resolve_s3_datasets(ws_id, payload)
    except HTTPException:
        resolved_s3 = []
    # 预览补 secret_ref (不查 key 存在, 只渲染)
    own = f"{sanitize_dns_label(username, fallback='user')}-secrets"
    for s in payload.env_secrets:
        s.secret_ref = own
    cr = _render_cr(
        payload=payload, ws_id=str(ws_id), k8s_ns=k8s_ns,
        name=f"{payload.display_name}-xxxxxxxxxx",
        rayjob_id="<preview>", creator_id=creator_id,
        resolved_fsx=resolved_fsx, resolved_s3=resolved_s3,
    )
    return _dump_cr_yaml(cr)


async def create_rayjob_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    ws_id: Any,
    payload: RayJobCreate,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    del db
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    await _assert_instance_type_allowed(hp, ws_id, payload.head_instance_type)
    await _assert_instance_type_allowed(hp, ws_id, payload.worker_instance_type)

    name = make_dns_name(
        payload.display_name, fallback="rayjob", max_total=RAYJOB_NAME_MAX
    )
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    creator_display_name = (
        current_user.get("display_name")
        or current_user.get("email")
        or creator_id
    )

    # 存储/env secret 授权反查 (不信前端; 越权/缺失 → 4xx)
    resolved_fsx = await _resolve_fsx_mounts(ws_id, username, payload)
    resolved_s3 = await _resolve_s3_datasets(ws_id, payload)
    await _resolve_env_secrets(k8s, k8s_ns, username, payload)

    row = await crud.create(
        None,
        workspace_id=ws_id,
        creator_user_id=creator_id,
        creator_display_name=creator_display_name,
        name=name,
        display_name=payload.display_name,
        description=payload.description,
        k8s_namespace=k8s_ns,
        k8s_cr_name=name,
        head_image=payload.head_image,
        worker_image=payload.worker_image,
        extra_fsx_mounts=resolved_fsx,
        s3_datasets=resolved_s3,
        entry_script_path=payload.entry_script_path,
        worker_replicas=payload.worker_replicas,
        head_instance_type=payload.head_instance_type,
        head_gpu=payload.head_gpu,
        head_cpu_request_millicores=payload.head_cpu_request_millicores,
        head_cpu_limit_millicores=payload.head_cpu_limit_millicores,
        head_memory_request_mib=payload.head_memory_request_mib,
        head_memory_limit_mib=payload.head_memory_limit_mib,
        head_efa=payload.head_efa,
        worker_instance_type=payload.worker_instance_type,
        gpu_per_node=payload.gpu_per_node,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        efa_per_node=payload.efa_per_node,
        max_run_hours=payload.max_run_hours,
        ttl_seconds_after_finished=payload.ttl_seconds_after_finished,
        backoff_limit=payload.backoff_limit,
        env=payload.env or {},
        env_secrets=[s.model_dump() for s in payload.env_secrets],
        run_as_root=payload.run_as_root,
        labels=validate_user_labels(payload.labels),
    )

    cr = _render_cr(
        payload=payload, ws_id=str(ws_id), k8s_ns=k8s_ns, name=name,
        rayjob_id=str(row["id"]), creator_id=creator_id,
        resolved_fsx=resolved_fsx, resolved_s3=resolved_s3,
    )

    # 下发 CR; 失败回滚 DDB 行 (照 dynamo, ★回滚失败 log 不静默)
    try:
        await k8s.create_rayjob(k8s_ns, cr)
    except K8sAPIError as exc:
        try:
            await crud.delete(None, row)
        except Exception:
            logger.warning("rayjob.create.rollback_ddb_fail", id=str(row["id"]), name=name)
        logger.warning(
            "rayjob.create.k8s_fail", name=name, code=exc.code, msg=exc.message
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s create RayJob failed: {exc.message}",
        ) from exc

    logger.info("rayjob.create.ok", id=str(row["id"]), name=name)

    from app.modules.rayjob.orchestration.lifecycle import audit_rayjob
    await audit_rayjob(row, current_user, "rayjob.create")

    return row
