"""llm-d 创建编排 (分支B) · 授权 FSx 反查 + 一组资源下发 (非单 CR)。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import t
from app.core.labels import validate_user_labels
from app.core.logging import get_logger
from app.adapters.k8s.workspace_resources import s3_pv_name, s3_pvc_name
from app.core.naming import LLMD_NAME_MAX, make_dns_name
from app.modules.llmd.api.schemas import LlmdCreate
from app.modules.llmd.domain.cr import render_llmd_resources
from app.modules.llmd.persistence import crud
from app.modules.workspace import crud as ws_crud
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

_FALLBACK_K8S_NS = "default"
_S3_DEFAULT_REGION = "us-west-2"
# S3 模型盘容器挂载点 (S3 无开发机 mount_path 概念, 固定; FSx 用授权 mount_path 跟开发机一致)
_S3_MODEL_MOUNT = "/model"

# OTel 集群真值 (worker/gateway 采集 sgl_* → 中央 collector → AMP; 与 dynamo 同一 collector)。
# TODO(集群解析): 后续从 settings/集群 discovery 拿, 暂硬编。
_OTEL_IMAGE = "602401143452.dkr.ecr.us-west-2.amazonaws.com/hyperpod/otel_collector:v1775584612408"
_OTEL_ENDPOINT = "hyperpod-otel-collector.hyperpod-observability:4317"


async def _assert_instance_type_allowed(hp: Any, ws_id: Any, instance_type: str) -> None:
    """机型必须在 ws ComputeQuota 已分配机型内 (API 公网, 防越权; 同 dynamo)。"""
    from app.modules.quota.orchestration.workspace_quota import get_workspace_quota

    quota = await get_workspace_quota(None, hp, ws_id)
    allowed = {r.instance_type for r in (quota.resources or [])}
    if instance_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t(
                "llmd.instance_type_not_allowed",
                instance_type=instance_type,
                allowed=sorted(allowed) or t("llmd.allowed_none"),
            ),
        )


async def _resolve_fsx_pvc(
    ws_id: Any, username: str, pvc_name: str
) -> tuple[str, str]:
    """按 pvc_name 反查该 user 被授权的 FSx, 返回 (pvc_name, mount_path) 真值 (照 dynamo)。

    只接受该 user 在该 ws 被授权的 FSx; 不在授权列表 → 403 (防绕前端越权挂别 team 盘)。
    """
    from app.modules.devinstance.orchestration.pvcs import list_permitted_mounts

    permitted = await list_permitted_mounts(str(ws_id), username)
    by_pvc = {p.name: p for p in permitted}
    p = by_pvc.get(pvc_name)
    if p is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("llmd.fsx_not_authorized", pvc_name=pvc_name),
        )
    return p.name, (p.mount_path or "")


async def _assert_s3_bucket_allowed(ws_id: Any, bucket: str) -> str:
    """校验 bucket ∈ ws 已挂 S3 的 bucket 集合 (防越权挂任意桶; 照 dynamo _resolve_s3)。

    返回该 bucket 在 ws 挂载里记录的 region (自建 PV 用); 没有则回退默认 region。
    prefix 用户自由填 (桶内自己的事, 不校验)。
    """
    from app.modules.workspace.orchestration.s3 import list_workspace_s3_flow

    mounts = await list_workspace_s3_flow(str(ws_id))
    region = next(
        (m.get("region") for m in mounts if m.get("bucket_name") == bucket and m.get("region")),
        None,
    )
    if not any(m.get("bucket_name") == bucket for m in mounts):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("llmd.s3_bucket_not_mounted", bucket=bucket),
        )
    return region or _S3_DEFAULT_REGION


def _dump_resources_yaml(resources: list[dict[str, Any]]) -> str:
    """一组资源 dict → 多文档 YAML (含换行 str 走 literal block |; 同 dynamo _dump_cr_yaml)。"""
    import yaml as _yaml

    class _BlockDumper(_yaml.SafeDumper):
        pass

    def _str_rep(dumper: _yaml.Dumper, data: str) -> Any:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _BlockDumper.add_representer(str, _str_rep)
    return _yaml.dump_all(
        resources, Dumper=_BlockDumper, sort_keys=False, default_flow_style=False,
        allow_unicode=True,
    )


def _render_resources_from_payload(
    *,
    payload: LlmdCreate,
    name: str,
    namespace: str,
    llmd_id: str,
    ws_id: str,
    creator_id: str,
    model_pvc: str,
    model_mount_path: str,
) -> list[dict[str, Any]]:
    """渲一组 llm-d 资源 · create 与 preview 共用 → 预览即真相。"""
    return render_llmd_resources(
        name=name,
        namespace=namespace,
        llmd_id=llmd_id,
        workspace_id=ws_id,
        creator_id=creator_id,
        launch_script=payload.launch_script,
        model_pvc=model_pvc,
        model_mount_path=model_mount_path,
        gpu_instance_type=payload.gpu_instance_type,
        gateway_instance_type=payload.gateway_instance_type,
        otel_endpoint=_OTEL_ENDPOINT,
        otel_image=_OTEL_IMAGE,
        replicas=payload.replicas,
        nodes_per_replica=payload.nodes_per_replica,
        gpu_per_pod=payload.gpu_per_pod,
        efa_per_pod=payload.efa_per_pod,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        gateway_image=payload.gateway_image,
        sglang_image=payload.sglang_image,
        gateway_replicas=payload.gateway_replicas,
        gateway_extra_args=list(payload.gateway_extra_args),
        gateway_cpu_request_millicores=payload.gateway_cpu_request_millicores,
        gateway_cpu_limit_millicores=payload.gateway_cpu_limit_millicores,
        gateway_memory_request_mib=payload.gateway_memory_request_mib,
        gateway_memory_limit_mib=payload.gateway_memory_limit_mib,
        expose_alb=payload.expose_alb,
    )


async def preview_llmd_flow(
    hp: Any, ws_id: Any, payload: LlmdCreate, current_user: dict[str, Any]
) -> str:
    """渲最终资源组 YAML, 不创建 · 与 create 共用渲染 → 预览即真相。"""
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    await _assert_instance_type_allowed(hp, ws_id, payload.gpu_instance_type)
    await _assert_instance_type_allowed(hp, ws_id, payload.gateway_instance_type)
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    # 预览: 与 create 一致 → 预览即真相; 授权失败不中断 (model_pvc 只影响挂载, 用占位)
    # FSx 挂授权 mount_path (跟开发机一致), S3 挂 /model (兜底)
    model_pvc = payload.model_pvc or "<model-pvc>"
    model_mount_path = _S3_MODEL_MOUNT
    try:
        if payload.model_source_type == "s3":
            # preview 不真建 PV, model_pvc 用占位 (prefix 指到模型目录, 挂 /model)
            await _assert_s3_bucket_allowed(ws_id, payload.s3_bucket or "")
            model_pvc = "<s3-pvc-on-create>"
        elif payload.model_pvc:
            model_pvc, mp = await _resolve_fsx_pvc(ws_id, creator_id, payload.model_pvc)
            model_mount_path = mp or _S3_MODEL_MOUNT
    except HTTPException:
        if payload.model_source_type == "s3":
            model_pvc = "<s3-pvc-on-create>"
    resources = _render_resources_from_payload(
        payload=payload,
        # 占位与真名同长, 便于看出会不会超限 (真名只在 create 时派生)
        name=f"{payload.display_name}-xxxxxxxxxx",
        namespace=k8s_ns,
        llmd_id="<preview>",
        ws_id=str(ws_id),
        creator_id=creator_id,
        model_pvc=model_pvc,
        model_mount_path=model_mount_path,
    )
    return _dump_resources_yaml(resources)


async def create_llmd_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    ws_id: Any,
    payload: LlmdCreate,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    del db
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")
    # ① 机型配额校验 (gateway CPU 池 + worker GPU 池 都校验)
    await _assert_instance_type_allowed(hp, ws_id, payload.gpu_instance_type)
    await _assert_instance_type_allowed(hp, ws_id, payload.gateway_instance_type)

    # display_name 已由 schema 保证 DNS 合法; 唯一性靠随机后缀, 不查重
    name = make_dns_name(
        payload.display_name, fallback="llmd", max_total=LLMD_NAME_MAX
    )
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    creator_display_name = (
        current_user.get("display_name") or current_user.get("email") or creator_id
    )

    # ② 模型源: fsx 走授权 FSx 反查; s3 校验 bucket 授权后自建专属 PV/PVC。
    #   S3 mount_id = 本 llmd 的 name (唯一, delete 时同名推出); pvc 名确定 → 先算, ④ 再真建。
    s3_region: str | None = None
    if payload.model_source_type == "s3":
        s3_region = await _assert_s3_bucket_allowed(ws_id, payload.s3_bucket or "")
        model_pvc = s3_pvc_name(name)  # prefix 指到模型目录 → 挂载点根即模型 (脚本里 /model)
        model_mount_path = _S3_MODEL_MOUNT
    else:
        # FSx 挂授权 mount_path (跟开发机/训练一致, 脚本 --model-path 原样写开发机路径)
        model_pvc, mp = await _resolve_fsx_pvc(
            ws_id, creator_id, payload.model_pvc or ""
        )
        model_mount_path = mp or _S3_MODEL_MOUNT

    # ③ crud.create 写 DDB 拿 id
    row = await crud.create(
        None,
        workspace_id=ws_id,
        creator_user_id=creator_id,
        creator_display_name=creator_display_name,
        name=name,
        display_name=payload.display_name,
        description=payload.description,
        k8s_namespace=k8s_ns,
        k8s_name=name,
        model_source_type=payload.model_source_type,
        launch_script=payload.launch_script,
        model_pvc=model_pvc,
        s3_bucket=payload.s3_bucket,
        s3_prefix=payload.s3_prefix,
        gpu_instance_type=payload.gpu_instance_type,
        gateway_instance_type=payload.gateway_instance_type,
        replicas=payload.replicas,
        nodes_per_replica=payload.nodes_per_replica,
        gpu_per_pod=payload.gpu_per_pod,
        efa_per_pod=payload.efa_per_pod,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        gateway_image=payload.gateway_image,
        sglang_image=payload.sglang_image,
        gateway_replicas=payload.gateway_replicas,
        gateway_extra_args=list(payload.gateway_extra_args),
        gateway_cpu_request_millicores=payload.gateway_cpu_request_millicores,
        gateway_cpu_limit_millicores=payload.gateway_cpu_limit_millicores,
        gateway_memory_request_mib=payload.gateway_memory_request_mib,
        gateway_memory_limit_mib=payload.gateway_memory_limit_mib,
        expose_alb=payload.expose_alb,
        labels=validate_user_labels(payload.labels),
    )

    # ④ S3 自建 PV+PVC (mount_id=name); 失败 → 回滚 DDB + 已建的 PV/PVC
    if payload.model_source_type == "s3":
        workspace_name = (ws.get("metadata_json") or {}).get("name") or ws.get("display_name") or name
        s3_pv: str | None = None
        s3_pvc: str | None = None
        try:
            s3_pv = await k8s.create_s3_pv(
                workspace_id=str(ws_id),
                workspace_name=workspace_name,
                namespace=k8s_ns,
                bucket_name=payload.s3_bucket or "",
                region=s3_region or _S3_DEFAULT_REGION,
                mount_id=name,
                prefix=payload.s3_prefix or "",
            )
            s3_pvc = await k8s.create_s3_pvc(
                namespace=k8s_ns,
                workspace_name=workspace_name,
                bucket_name=payload.s3_bucket or "",
                pv_full_name=s3_pv,
                mount_id=name,
            )
        except K8sAPIError as exc:
            if s3_pvc:
                try:
                    await k8s.delete_pvc(k8s_ns, s3_pvc)
                except Exception:
                    logger.warning("llmd.create.rollback_s3_pvc_fail", name=name)
            if s3_pv:
                try:
                    await k8s.delete_pv(s3_pv)
                except Exception:
                    logger.warning("llmd.create.rollback_s3_pv_fail", name=name)
            try:
                await crud.delete(None, row)
            except Exception:
                logger.warning("llmd.create.rollback_ddb_fail", id=str(row["id"]), name=name)
            logger.warning("llmd.create.s3_pv_fail", name=name, code=exc.code, msg=exc.message)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"k8s create S3 PV/PVC failed: {exc.message}",
            ) from exc

    # ⑤ 渲染一组资源
    resources = _render_resources_from_payload(
        payload=payload,
        name=name,
        namespace=k8s_ns,
        llmd_id=str(row["id"]),
        ws_id=str(ws_id),
        creator_id=creator_id,
        model_pvc=model_pvc,
        model_mount_path=model_mount_path,
    )

    # ⑥ 下发; 失败 → 回滚 (DDB 行 + llmd 资源 + S3 自建 PV/PVC), 回滚失败只 log.warning 不静默
    try:
        await k8s.apply_llmd_resources(k8s_ns, resources)
    except K8sAPIError as exc:
        try:
            await crud.delete(None, row)
        except Exception:
            logger.warning("llmd.create.rollback_ddb_fail", id=str(row["id"]), name=name)
        try:
            await k8s.delete_llmd_resources(k8s_ns, name)
        except Exception:
            logger.warning("llmd.create.rollback_k8s_fail", name=name)
        if payload.model_source_type == "s3":
            try:
                await k8s.delete_pvc(k8s_ns, s3_pvc_name(name))
            except Exception:
                logger.warning("llmd.create.rollback_s3_pvc_fail", name=name)
            try:
                await k8s.delete_pv(s3_pv_name(str(ws_id), name))
            except Exception:
                logger.warning("llmd.create.rollback_s3_pv_fail", name=name)
        logger.warning("llmd.create.k8s_fail", name=name, code=exc.code, msg=exc.message)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s apply llmd resources failed: {exc.message}",
        ) from exc

    logger.info("llmd.create.ok", id=str(row["id"]), name=row["name"], k8s_name=row["k8s_name"])

    from app.modules.llmd.orchestration.lifecycle import audit_llmd
    await audit_llmd(row, current_user, "llmd.create")

    return row
