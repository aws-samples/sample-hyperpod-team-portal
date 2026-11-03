"""Dynamo 创建编排 · 对齐推理/训练: 授权 FSx/S3 反查 + 启动脚本。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import t
from app.core.labels import validate_user_labels
from app.core.logging import get_logger
from app.core.naming import sanitize_dns_label
from app.modules.dynamo.api.schemas import DynamoCreate
from app.modules.dynamo.domain.cr import (
    _FALLBACK_MOUNT_PATH,
    otel_configmap_name,
    render_dynamo_graph_deployment_cr,
    render_dynamo_otel_config,
)
from app.modules.dynamo.persistence import crud
from app.modules.workspace import crud as ws_crud
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

_FALLBACK_K8S_NS = "default"


async def _assert_instance_type_allowed(hp: Any, ws_id: Any, instance_type: str) -> None:
    """机型必须在 ws ComputeQuota 已分配机型内 (API 公网, 防越权; 同 inference)。"""
    from app.modules.quota.orchestration.workspace_quota import get_workspace_quota

    quota = await get_workspace_quota(None, hp, ws_id)
    allowed = {r.instance_type for r in (quota.resources or [])}
    if instance_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t(
                "dynamo.instance_type_not_allowed",
                instance_type=instance_type,
                allowed=sorted(allowed) or t("dynamo.allowed_none"),
            ),
        )


async def _resolve_fsx_pvc(
    ws_id: Any, username: str, pvc_name: str
) -> tuple[str, str]:
    """按 pvc_name 反查该 user 被授权的 FSx, 返回 (pvc_name, mount_path) 真值。

    安全 (照训练 _resolve_fsx_mounts): 只接受该 user 在该 ws 被授权的 FSx;
    pvc_name 不在授权列表 → 403 (防绕前端越权挂别 team 盘)。mount_path 取授权真值。
    """
    from app.modules.devinstance.orchestration.pvcs import list_permitted_mounts

    permitted = await list_permitted_mounts(str(ws_id), username)
    by_pvc = {p.name: p for p in permitted}
    p = by_pvc.get(pvc_name)
    if p is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("dynamo.fsx_not_authorized", pvc_name=pvc_name),
        )
    return p.name, (p.mount_path or "")


async def _resolve_s3(ws_id: Any, bucket_name: str) -> None:
    """校验 S3 bucket 在 ws 已挂载列表内 (防越权填任意 bucket; 同训练)。"""
    from app.modules.workspace.orchestration.s3 import list_workspace_s3_flow

    mounts = await list_workspace_s3_flow(str(ws_id))
    buckets = {m.get("bucket_name") for m in mounts}
    if bucket_name not in buckets:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("dynamo.s3_bucket_not_mounted", bucket=bucket_name),
        )


def _dump_cr_yaml(cr: dict[str, Any]) -> str:
    """CR dict → YAML (含换行 str 走 literal block |; 同 inference _dump_cr_yaml)。"""
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


def _render_cr_from_payload(
    *,
    payload: DynamoCreate,
    name: str,
    namespace: str,
    dynamo_id: str,
    ws_id: str,
    creator_id: str,
    fsx_pvc_name: str,
    fsx_mount_path: str,
) -> dict[str, Any]:
    """渲 Dynamo CR · create 与 preview 共用 → 预览即真相。"""
    return render_dynamo_graph_deployment_cr(
        name=name,
        namespace=namespace,
        dynamo_id=dynamo_id,
        workspace_id=ws_id,
        creator_id=creator_id,
        fsx_pvc_name=fsx_pvc_name,
        fsx_mount_path=fsx_mount_path,
        launch_script=payload.launch_script,
        instance_type=payload.instance_type,
        backend_framework=payload.backend_framework,
        image=payload.image,
        node_count=payload.node_count,
        replicas=payload.replicas,
        gpu_per_worker=payload.gpu_per_worker,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        efa_per_worker=payload.efa_per_worker,
        run_as_root=payload.run_as_root,
        user_labels=validate_user_labels(payload.labels),
    )


async def preview_dynamo_flow(
    hp: Any, ws_id: Any, payload: DynamoCreate, current_user: dict[str, Any]
) -> str:
    """渲最终 CR YAML, 不创建 · 与 create 共用渲染 → 预览即真相。"""
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    # 预览: 做授权反查拿真 mount_path (与 create 一致 → 预览即真相); FSx 才查
    fsx_pvc = payload.fsx_pvc_name or "<fsx-pvc>"
    fsx_mount_path = _FALLBACK_MOUNT_PATH
    if payload.model_source_type == "fsx" and payload.fsx_pvc_name:
        try:
            fsx_pvc, fsx_mount_path = await _resolve_fsx_pvc(
                ws_id, creator_id, payload.fsx_pvc_name
            )
        except HTTPException:
            # 预览不因授权失败中断 (真 create 会拦); 挂载点回退兜底
            pass
    cr = _render_cr_from_payload(
        payload=payload,
        name=sanitize_dns_label(payload.name, fallback="dynamo"),
        namespace=k8s_ns,
        dynamo_id="<preview>",
        ws_id=str(ws_id),
        creator_id=creator_id,
        fsx_pvc_name=fsx_pvc,
        fsx_mount_path=fsx_mount_path,
    )
    return _dump_cr_yaml(cr)


async def create_dynamo_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    ws_id: Any,
    payload: DynamoCreate,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    del db
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)

    name = sanitize_dns_label(payload.name, fallback="dynamo")
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    creator_display_name = (
        current_user.get("display_name") or current_user.get("email") or creator_id
    )

    # 模型来源授权反查 (不信前端传的挂载真值)
    fsx_pvc_name: str | None = None
    fsx_mount_path: str | None = None
    s3_d: dict[str, Any] | None = None
    if payload.model_source_type == "fsx":
        fsx_pvc_name, fsx_mount_path = await _resolve_fsx_pvc(
            ws_id, creator_id, payload.fsx_pvc_name or ""
        )
    elif payload.model_source_type == "s3" and payload.s3:
        await _resolve_s3(ws_id, payload.s3.bucket_name)
        s3_d = payload.s3.model_dump()

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
        backend_framework=payload.backend_framework,
        image=payload.image,
        model_source_type=payload.model_source_type,
        fsx_pvc_name=fsx_pvc_name,
        fsx_mount_path=fsx_mount_path,
        s3=s3_d,
        launch_script=payload.launch_script,
        node_count=payload.node_count,
        replicas=payload.replicas,
        instance_type=payload.instance_type,
        gpu_per_worker=payload.gpu_per_worker,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        efa_per_worker=payload.efa_per_worker,
        run_as_root=payload.run_as_root,
        labels=validate_user_labels(payload.labels),
    )

    cr = _render_cr_from_payload(
        payload=payload,
        name=name,
        namespace=k8s_ns,
        dynamo_id=str(row["id"]),
        ws_id=str(ws_id),
        creator_id=creator_id,
        fsx_pvc_name=fsx_pvc_name or "<s3-not-mounted>",
        fsx_mount_path=fsx_mount_path or "/fsx",
    )

    # 先建 OTel configmap (sidecar 挂它 scrape dynamo_* → 推中央 collector, 监控);
    # 必须在下发 CR 前建, 否则 sidecar 起来挂不到 configmap。失败不阻断 (监控非核心, 只 log)。
    try:
        await k8s.apply_config_map(
            k8s_ns,
            otel_configmap_name(name),
            {"config.yaml": render_dynamo_otel_config(name, k8s_ns)},
        )
    except K8sAPIError as exc:
        logger.warning("dynamo.create.otel_cm_fail", name=name, code=exc.code, msg=exc.message)

    try:
        await k8s.create_dynamo_deployment(k8s_ns, cr)
    except K8sAPIError as exc:
        try:
            await crud.delete(None, row)
        except Exception:
            logger.warning("dynamo.create.rollback_ddb_fail", id=str(row["id"]), name=name)
        try:
            await k8s.delete_config_map(k8s_ns, otel_configmap_name(name))
        except Exception:
            logger.warning("dynamo.create.rollback_cm_fail", name=name)
        logger.warning("dynamo.create.k8s_fail", name=name, code=exc.code, msg=exc.message)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s create DynamoGraphDeployment failed: {exc.message}",
        ) from exc

    logger.info("dynamo.create.ok", id=str(row["id"]), name=row["name"], k8s_cr=name)

    from app.modules.dynamo.orchestration.lifecycle import audit_dynamo
    await audit_dynamo(row, current_user, "dynamo.create")

    return row
