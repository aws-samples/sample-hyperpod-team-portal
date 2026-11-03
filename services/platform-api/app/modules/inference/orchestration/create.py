"""Inference 创建编排 (DDB-only)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import s3 as s3_adapter
from app.adapters.aws.s3 import S3APIError
from app.core.i18n import t
from app.core.logging import get_logger
from app.core.naming import INFERENCE_NAME_MAX, make_dns_name
from app.modules.inference.api.schemas import InferenceCreate
from app.core.labels import validate_user_labels
from app.modules.inference.domain.cr import render_inference_endpoint_cr
from app.modules.inference.persistence import crud
from app.modules.workspace import crud as ws_crud
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

_FALLBACK_K8S_NS = "default"


async def _assert_instance_type_allowed(hp: Any, ws_id: Any, instance_type: str) -> None:
    """校验 instance_type 必须在该 workspace ComputeQuota 已分配的机型内。

    安全 (API 已公网): 推理机型只能选 ws 配额里真实分配的 instance group, 不能
    自由填任意机型 (防越权用未授权/集群没有的机型)。不在配额 → 403。
    ws 无 ComputeQuota 时 get_workspace_quota 抛 404, 透传 (无配额不能建推理)。
    """
    from app.modules.quota.orchestration.workspace_quota import get_workspace_quota

    quota = await get_workspace_quota(None, hp, ws_id)
    allowed = {r.instance_type for r in (quota.resources or [])}
    if instance_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t(
                "inference.instance_type_not_allowed",
                instance_type=instance_type,
                allowed=sorted(allowed) or t("inference.allowed_none"),
            ),
        )


def _dump_cr_yaml(cr: dict[str, Any]) -> str:
    """CR dict → YAML 字符串 · 含换行的 str (如 command 脚本) 走 literal block (|)。

    与训练 _dump_cr_yaml 同实现 (专属 Dumper 不污染全局)。
    """
    import yaml as _yaml

    class _BlockDumper(_yaml.SafeDumper):
        pass

    def _str_rep(dumper: _yaml.Dumper, data: str) -> Any:
        if "\n" in data:
            return dumper.represent_scalar(
                "tag:yaml.org,2002:str", data, style="|"
            )
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _BlockDumper.add_representer(str, _str_rep)
    return _yaml.dump(
        cr,
        Dumper=_BlockDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


async def _archive_cr_yaml(
    *,
    ws: dict[str, Any],
    ws_id: str,
    creator_id: str,
    task_name: str,
    cr: dict[str, Any],
) -> str | None:
    """存真实下发的 CR YAML 到 S3: s3://<bucket>/<ws>/<user>/<task>/test-<task>.yaml.

    bucket 取 workspace 已挂的第一个 s3_mount。ws 没挂 S3 → 跳过 (返 None)。
    上传失败不阻断 (CR 已下发成功), 只 log。与训练 train-<task>.yaml 对应, 推理用 test-。
    """
    mounts = (ws.get("metadata_json") or {}).get("s3_mounts") or []
    if not mounts:
        logger.info("inference.create.yaml_archive_skip", reason="no_s3_mount", id=ws_id)
        return None
    mount = mounts[0]
    bucket = mount.get("bucket_name")
    if not bucket:
        logger.info("inference.create.yaml_archive_skip", reason="no_bucket", id=ws_id)
        return None
    key = f"{ws_id}/{creator_id}/{task_name}/test-{task_name}.yaml"
    try:
        uri = await s3_adapter.put_text(
            bucket=bucket,
            key=key,
            body=_dump_cr_yaml(cr),
            region=mount.get("region") or None,
        )
        logger.info("inference.create.yaml_archived", uri=uri)
        return uri
    except S3APIError as exc:
        logger.warning(
            "inference.create.yaml_archive_fail",
            bucket=bucket,
            key=key,
            code=exc.code,
            msg=exc.message,
        )
        return None


def _render_cr_from_payload(
    *,
    payload: InferenceCreate,
    name: str,
    model_name: str,
    namespace: str,
    inference_id: str,
    ws_id: str,
    creator_id: str,
    fsx_d: dict[str, Any] | None,
    s3_d: dict[str, Any] | None,
    hf_d: dict[str, Any] | None,
    l2_d: dict[str, Any],
) -> dict[str, Any]:
    """渲染 IEC CR · create 与 preview 共用 → 预览即真相。"""
    return render_inference_endpoint_cr(
        name=name,
        namespace=namespace,
        inference_id=inference_id,
        workspace_id=ws_id,
        creator_id=creator_id,
        model_name=model_name,
        model_source_type=payload.model_source_type,
        model_mount_path=payload.model_mount_path,
        fsx=fsx_d,
        s3=s3_d,
        hf=hf_d,
        image=payload.image,
        container_port=payload.container_port,
        sglang_extra_args=list(payload.sglang_extra_args),
        sglang_command=list(payload.sglang_command),
        sglang_args=list(payload.sglang_args),
        launch_script=payload.launch_script,
        invocation_endpoint=payload.invocation_endpoint,
        instance_type=payload.instance_type,
        gpu_per_replica=payload.gpu_per_replica,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        replicas=payload.replicas,
        routing_strategy=payload.routing_strategy,
        l2_kv_cache=l2_d,
        metrics_enabled=payload.metrics_enabled,
        public_endpoint=payload.public_endpoint,
        user_labels=validate_user_labels(payload.labels),
        env=dict(payload.env or {}),
    )


async def preview_inference_flow(
    hp: Any,
    ws_id: Any,
    payload: InferenceCreate,
    current_user: dict[str, Any],
) -> str:
    """渲染最终要下发的 IEC CR YAML, 不创建 / 不写 DDB · 返回 YAML 字符串。

    与 create 共用 _render_cr_from_payload → 预览即真相。
    """
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    # 占位与真名同长, 便于看出会不会超限 (真名只在 create 时派生)
    preview_name = f"{payload.display_name}-xxxxxxxxxx"
    cr = _render_cr_from_payload(
        payload=payload,
        name=preview_name,
        model_name=preview_name,
        namespace=k8s_ns,
        inference_id="<preview>",
        ws_id=str(ws_id),
        creator_id=creator_id,
        fsx_d=payload.fsx.model_dump() if payload.fsx else None,
        s3_d=payload.s3.model_dump() if payload.s3 else None,
        hf_d=payload.huggingface.model_dump() if payload.huggingface else None,
        l2_d=payload.l2_kv_cache.model_dump(),
    )
    return _dump_cr_yaml(cr)


async def create_inference_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    ws_id: Any,
    payload: InferenceCreate,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    del db
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )

    # 机型必须在 ws ComputeQuota 已分配机型内 (API 公网, 防越权填任意机型)
    await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)

    # display_name 已由 schema 保证 DNS 合法; 唯一性靠随机后缀, 不查重
    name = make_dns_name(
        payload.display_name, fallback="infer", max_total=INFERENCE_NAME_MAX
    )

    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    k8s_endpoint_name = name

    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    creator_display_name = (
        current_user.get("display_name") or current_user.get("email") or creator_id
    )

    fsx_d = payload.fsx.model_dump() if payload.fsx else None
    s3_d = payload.s3.model_dump() if payload.s3 else None
    hf_d = payload.huggingface.model_dump() if payload.huggingface else None
    l2_d = payload.l2_kv_cache.model_dump()

    row = await crud.create(
        None,
        workspace_id=ws_id,
        creator_user_id=creator_id,
        creator_display_name=creator_display_name,
        name=name,
        display_name=payload.display_name,
        description=payload.description,
        k8s_namespace=k8s_ns,
        k8s_endpoint_name=k8s_endpoint_name,
        framework=payload.framework,
        model_name=name,
        model_mount_path=payload.model_mount_path,
        model_source_type=payload.model_source_type,
        fsx=fsx_d,
        s3=s3_d,
        huggingface=hf_d,
        image=payload.image,
        invocation_endpoint=payload.invocation_endpoint,
        container_port=payload.container_port,
        sglang_extra_args=list(payload.sglang_extra_args),
        launch_script=payload.launch_script,
        instance_type=payload.instance_type,
        gpu_per_replica=payload.gpu_per_replica,
        cpu_request_millicores=payload.cpu_request_millicores,
        cpu_limit_millicores=payload.cpu_limit_millicores,
        memory_request_mib=payload.memory_request_mib,
        memory_limit_mib=payload.memory_limit_mib,
        replicas=payload.replicas,
        routing_strategy=payload.routing_strategy,
        l2_kv_cache=l2_d,
        metrics_enabled=payload.metrics_enabled,
        public_endpoint=payload.public_endpoint,
        labels=validate_user_labels(payload.labels),
        env=dict(payload.env or {}),
    )

    cr = _render_cr_from_payload(
        payload=payload,
        name=k8s_endpoint_name,
        model_name=name,
        namespace=k8s_ns,
        inference_id=str(row["id"]),
        ws_id=str(ws_id),
        creator_id=creator_id,
        fsx_d=fsx_d,
        s3_d=s3_d,
        hf_d=hf_d,
        l2_d=l2_d,
    )

    try:
        await k8s.create_inference_endpoint(k8s_ns, cr)
    except K8sAPIError as exc:
        # K8s 失败 → 回滚 DDB row
        try:
            await crud.delete(None, row)
        except Exception:
            pass
        logger.warning(
            "inference.create.k8s_fail",
            name=name,
            code=exc.code,
            msg=exc.message,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s create InferenceEndpointConfig failed: {exc.message}",
        ) from exc

    logger.info(
        "inference.create.ok",
        id=str(row["id"]),
        name=row["name"],
        k8s_cr=k8s_endpoint_name,
    )

    # 存真实下发的 CR YAML 到 S3 (ws 自己的桶). 失败不阻断.
    yaml_uri = await _archive_cr_yaml(
        ws=ws,
        ws_id=str(ws_id),
        creator_id=creator_id,
        task_name=name,
        cr=cr,
    )
    if yaml_uri:
        row["yaml_s3_uri"] = yaml_uri

    # 审计 (append-only, 失败不阻断主流程)
    from app.modules.inference.orchestration.lifecycle import audit_inference
    await audit_inference(row, current_user, "inference.create")

    return row
