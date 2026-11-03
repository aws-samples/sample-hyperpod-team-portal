"""Training job 创建编排 (DDB-only)."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from fastapi import HTTPException, status

from app.adapters.aws import s3 as s3_adapter
from app.adapters.aws.s3 import S3APIError
from app.core.i18n import t
from app.core.labels import validate_user_labels
from app.core.logging import get_logger
from app.core.naming import TRAINING_NAME_MAX, make_dns_name, sanitize_dns_label
from app.modules.training.api.schemas import TrainingJobCreate
from app.modules.training.domain.cr import render_hp_pytorch_job_cr

# 直接导子模块而非走 orchestration 包 (__init__ 先导 create, 回头导包会循环)
from app.modules.training.orchestration.topology import resolve_topology_levels
from app.modules.training.persistence import crud
from app.modules.workspace import crud as ws_crud
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

_FALLBACK_K8S_NS = "default"


async def _resolve_env_secrets(
    k8s: K8sClient,
    k8s_ns: str,
    username: str,
    payload: TrainingJobCreate,
) -> None:
    """env_secrets: 补 secret_ref = 本人固定 secret 名 + 校验 key 存在。

    B2: 每人固定一把 <owner>-secrets, secret_ref 平台补 (用户只选 key, 天然只能用自己的);
    引用的 key 须真存在 (没建 → 400 引导先去建)。
    """
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
            t("training.secret_keys_missing", keys=", ".join(sorted(missing))),
        )


async def _assert_instance_type_allowed(
    hp: Any, ws_id: Any, instance_type: str | None
) -> None:
    """校验 instance_type 必须在该 workspace ComputeQuota 已分配的机型内。

    安全 (API 公网): 训练机型只能选 ws 配额真实分配的机型, 防越权用未授权/集群没有的
    机型。不在配额 → 403。instance_type 为空 (选填) 则跳过 (走 Kueue 自动分, 兼容旧)。
    """
    if not instance_type:
        return
    from app.modules.quota.orchestration.workspace_quota import get_workspace_quota

    quota = await get_workspace_quota(None, hp, ws_id)
    allowed = {r.instance_type for r in (quota.resources or [])}
    if instance_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t(
                "training.instance_type_not_allowed",
                instance_type=instance_type,
                allowed=sorted(allowed) or t("training.allowed_none"),
            ),
        )


def _compute_run_as_group(
    ws: dict[str, Any], resolved_fsx: list[dict[str, Any]]
) -> int | None:
    """runAsGroup 兜底链 (照开发机): ws primary_gid 优先 →
    第一个选中 FSx 的 gid → None (不设 securityContext)。
    """
    raw = (ws.get("metadata_json") or {}).get("primary_gid")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    for m in resolved_fsx:
        if m.get("gid") is not None:
            try:
                return int(m["gid"])
            except (TypeError, ValueError):
                continue
    return None


def _render_cr(
    *,
    payload: TrainingJobCreate,
    ws_id: str,
    k8s_ns: str,
    k8s_job_name: str,
    job_id: str,
    creator_id: str,
    resolved_s3_datasets: list[dict[str, Any]] | None = None,
    resolved_fsx_mounts: list[dict[str, Any]] | None = None,
    run_as_group: int | None = None,
) -> dict[str, Any]:
    """组装 render_hp_pytorch_job_cr 入参 → 返 CR dict。

    create 与 preview 共用同一份, 保证预览 YAML == 实际下发 (单一真相源)。
    resolved_s3_datasets / resolved_fsx_mounts: 调用方按引用反查授权得到的真值
    (替代 payload 里的引用)。run_as_group: ws primary_gid 兜底。
    """
    code_dict = payload.code.model_dump() if payload.code is not None else None
    # env_secrets → cr.py 渲 valueFrom.secretKeyRef (值不进 CR 明文)。
    env_secrets = [s.model_dump() for s in payload.env_secrets]
    s3_datasets_dict = resolved_s3_datasets or []
    fsx_dict = resolved_fsx_mounts or []
    # 所有选中 FSx 的 gid 进 supplementalGroups (去重; S3 1001 由 cr.py 补)
    fsx_gids = sorted({
        int(m["gid"]) for m in fsx_dict if m.get("gid") is not None
    })
    return render_hp_pytorch_job_cr(
        name=k8s_job_name,
        namespace=k8s_ns,
        image=payload.image,
        command=payload.command,
        node_count=payload.node_count,
        spares=payload.spares,
        gpu_per_node=payload.gpu_per_node,
        cpu_per_node_millicores=payload.cpu_per_node_millicores,
        memory_per_node_mib=payload.memory_per_node_mib,
        efa_per_node=payload.efa_per_node,
        training_job_id=job_id,
        workspace_id=ws_id,
        creator_id=creator_id,
        experiment_id=payload.experiment_id,
        priority_class=payload.priority_class,
        env=payload.env or {},
        env_secrets=env_secrets,
        code=code_dict,
        instance_type=payload.instance_type,
        run_as_group=run_as_group,
        fsx_supplemental_gids=fsx_gids,
        s3_datasets=s3_datasets_dict,
        extra_fsx_mounts=fsx_dict,
        clean_pod_policy=payload.clean_pod_policy,
        ttl_seconds_after_finished=payload.ttl_seconds_after_finished,
        job_max_retry_count=payload.job_max_retry_count,
        active_deadline_seconds=payload.active_deadline_seconds,
        run_policy_override=payload.run_policy_override,
        topology_mode=payload.topology_mode,
        topology_label=payload.topology_label,
        auto_wrap=payload.auto_wrap,
        user_labels=validate_user_labels(payload.labels),
    )


def _dump_cr_yaml(cr: dict[str, Any]) -> str:
    """CR dict → YAML 字符串 · 多行字符串 (如 command 里的脚本) 用 literal block (|)。

    默认 PyYAML 把含换行的 str 转义成 "...\\n..." (难读)。注册 representer 让
    含换行的 str 走 block style '|' → 脚本在 YAML 里显示成正常缩进多行, 人可读。
    用专属 Dumper 子类, 不污染全局 SafeDumper。
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
    """把真实下发的 CR YAML 存 S3: s3://<bucket>/<ws>/<user>/<task>/train-<task>.yaml.

    bucket 取 workspace 已挂的第一个 s3_mount (decision: ws 自己的桶)。
    ws 没挂 S3 → 跳过 (返回 None)。上传失败不阻断 (任务已下发成功), 只 log。
    """
    mounts = (ws.get("metadata_json") or {}).get("s3_mounts") or []
    if not mounts:
        logger.info("training.create.yaml_archive_skip", reason="no_s3_mount", id=ws_id)
        return None
    mount = mounts[0]
    bucket = mount.get("bucket_name")
    if not bucket:
        logger.info("training.create.yaml_archive_skip", reason="no_bucket", id=ws_id)
        return None
    key = f"{ws_id}/{creator_id}/{task_name}/train-{task_name}.yaml"
    try:
        uri = await s3_adapter.put_text(
            bucket=bucket,
            key=key,
            body=_dump_cr_yaml(cr),
            region=mount.get("region") or None,
        )
        logger.info("training.create.yaml_archived", uri=uri)
        return uri
    except S3APIError as exc:
        logger.warning(
            "training.create.yaml_archive_fail",
            bucket=bucket,
            key=key,
            code=exc.code,
            msg=exc.message,
        )
        return None


async def _resolve_s3_datasets(
    ws_id: Any, payload: TrainingJobCreate
) -> list[dict[str, Any]]:
    """按 payload.s3_datasets 的 mount_id 反查 ws 已挂 S3, 返回真值 dict 列表。

    安全: 只接受 ws 已挂载/授权的 S3 (list_workspace_s3_flow); mount_id 不在列表
    → 403 (防自由填任意 bucket 越权)。mount_path 等取 ws 挂载真值 (用户不可改)。
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
                t("training.s3_mount_not_allowed", mount_id=ref.mount_id),
            )
        resolved.append({
            "bucket": m.get("bucket_name") or "",
            "prefix": m.get("prefix") or "",
            "mount_path": m.get("mount_path") or "",
            "pvc_name": m.get("pvc_name") or "",
        })
    return resolved


async def _resolve_fsx_mounts(
    ws_id: Any, username: str, payload: TrainingJobCreate
) -> list[dict[str, Any]]:
    """按 payload.fsx_mounts 的 pvc_name 反查该 user 被授权的 FSx, 返回真值 dict 列表。

    安全: 只接受该 user 在该 ws 被授权的 FSx (list_permitted_mounts →
    MountPermissions)。pvc_name 不在授权列表 → 403 (防绕前端越权挂别 team 盘)。
    mount_path / read_only(access) / gid 全取授权真值, 不信前端传的。
    返回 dict: {pvc_name, mount_path, read_only, gid}。
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
                t("training.fsx_not_authorized", pvc_name=ref.pvc_name),
            )
        resolved.append({
            "pvc_name": p.name,
            "mount_path": p.mount_path or "",
            "read_only": (p.access == "ro"),
            "gid": p.gid,
        })
    return resolved


async def preview_training_job_flow(
    hp: Any,
    ws_id: Any,
    payload: TrainingJobCreate,
    current_user: dict[str, Any],
) -> str:
    """渲染最终 CR 但不下发 / 不写 DDB · 返回 YAML 字符串。

    与 create 共用 _render_cr → 预览的 = 实际跑的。run_policy_override 校验失败
    抛 RunPolicyValidationError, 由 router 转 422。
    """
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)
    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    # 预览不生成任务名 (真名只在 create 时派生一次)。占位与真名同长, 便于判断会不会
    # 超 TRAINING_NAME_MAX。
    preview_job_name = f"{payload.display_name}-xxxxxxxxxx"
    resolved_s3 = await _resolve_s3_datasets(ws_id, payload)
    resolved_fsx = await _resolve_fsx_mounts(ws_id, username, payload)
    # 补 secret_ref = 本人固定 secret 名 (预览不查 key 存在, 只渲染)
    _own_secret = f"{sanitize_dns_label(username, fallback='user')}-secrets"
    for _s in payload.env_secrets:
        _s.secret_ref = _own_secret
    cr = _render_cr(
        payload=payload,
        ws_id=str(ws_id),
        k8s_ns=k8s_ns,
        k8s_job_name=preview_job_name,
        job_id="<preview>",
        creator_id=creator_id,
        resolved_s3_datasets=resolved_s3,
        resolved_fsx_mounts=resolved_fsx,
        run_as_group=_compute_run_as_group(ws, resolved_fsx),
    )
    return _dump_cr_yaml(cr)


async def create_training_job_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    ws_id: Any,
    payload: TrainingJobCreate,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    del db
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )

    # 机型必须在 ws ComputeQuota 已分配机型内 (API 公网防越权)
    await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)

    # 只校验创建不校验 preview (改机型时预览不该先报错)
    if payload.topology_mode != "none" and payload.topology_label:
        levels = await resolve_topology_levels(k8s, payload.instance_type)
        allowed = {lv.node_label for lv in levels}
        if payload.topology_label not in allowed:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                t(
                    "training.topology_level_invalid",
                    label=payload.topology_label,
                    instance_type=payload.instance_type,
                    allowed=sorted(allowed) or t("training.allowed_none"),
                ),
            )

    # 任务名 = display_name + '-' + 10 位随机, 总长 ≤ TRAINING_NAME_MAX。
    # display_name 已由 schema 保证 DNS 合法且 ≤29, 这里纯拼接不清洗; 唯一性靠随机后缀,
    # 不查重。
    name = make_dns_name(
        payload.display_name, fallback="train", max_total=TRAINING_NAME_MAX
    )

    k8s_ns = ws.get("namespace") or _FALLBACK_K8S_NS
    k8s_job_name = name

    # env_secrets 引用的 Secret 必须是本人建的 (措施3/4 防越权用别人 secret)
    username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    await _resolve_env_secrets(k8s, k8s_ns, username, payload)

    run_policy_meta = {
        "clean_pod_policy": payload.clean_pod_policy,
        "ttl_seconds_after_finished": payload.ttl_seconds_after_finished,
        "active_deadline_seconds": payload.active_deadline_seconds,
        "job_max_retry_count": payload.job_max_retry_count,
    }

    code_dict = (
        payload.code.model_dump() if payload.code is not None else None
    )
    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    # S3 / FSx: 按引用反查授权真值 (越权 → 403)。存真值 + CR 用真值。
    s3_datasets_dict = await _resolve_s3_datasets(ws_id, payload)
    resolved_fsx = await _resolve_fsx_mounts(ws_id, username, payload)
    run_as_group = _compute_run_as_group(ws, resolved_fsx)

    creator_display_name = (
        current_user.get("display_name")
        or current_user.get("email")
        or creator_id
    )
    # job_id 同时作 DDB resource_id 与 CR label (training-job-id), 让 create 先写的
    # DDB 行与 informer 后续 watch 到的 CR 关联同一行。informer 用
    # upsert_resource_if_newer (整行 PutItem) → base._reconcile 先 get 旧行 merge
    # metadata, 只覆盖状态字段 (phase/started_at/...), 不冲 create 写的业务字段。
    # ★fsx_gid (demo-dev-02): 进 pod securityContext.
    job_id = _uuid.uuid4().hex
    metadata_json = {
        "run_policy": run_policy_meta,
        # 用户编辑的 runPolicy 裸 YAML 整段 (None=没编辑用默认); 克隆原样回填.
        "run_policy_override": payload.run_policy_override,
        "code": code_dict,
        # env_secrets 存 md (仅引用 name/key, 无 value) 供详情/克隆回填。
        "env_secrets": [s.model_dump() for s in payload.env_secrets],
        # FSx 全平等挂载 (反查授权真值), 存进 extra_fsx_mounts 供详情展示;
        # run_as_group = ws primary_gid 兜底 (securityContext runAsGroup)。
        "run_as_group": run_as_group,
        "instance_type": payload.instance_type,  # 选的机型 (nodeSelector)
        "s3_datasets": s3_datasets_dict,
        "extra_fsx_mounts": resolved_fsx,
        "experiment_id": payload.experiment_id,
        "priority_class": payload.priority_class,
        "spares": payload.spares,
        "topology_mode": payload.topology_mode,
        "topology_label": payload.topology_label,
        "labels": validate_user_labels(payload.labels),
    }

    # 1. 先写 DDB ResourceIndex (提交前落库, 参考推理 create_inference_flow)。
    row = await crud.create(
        None,
        workspace_id=ws_id,
        creator_user_id=creator_id,
        name=name,
        display_name=payload.display_name,
        description=payload.description,
        k8s_namespace=k8s_ns,
        k8s_job_name=k8s_job_name,
        image=payload.image,
        command=payload.command,
        node_count=payload.node_count,
        gpu_per_node=payload.gpu_per_node,
        cpu_per_node_millicores=payload.cpu_per_node_millicores,
        memory_per_node_mib=payload.memory_per_node_mib,
        efa_per_node=payload.efa_per_node,
        env_json=payload.env or {},
        metadata_json=metadata_json,
        resource_id=job_id,
    )
    # creator 显示名 (列表/详情冗余, 写入时拍快照)
    row["creator_display_name"] = creator_display_name

    cr = _render_cr(
        payload=payload,
        ws_id=str(ws_id),
        k8s_ns=k8s_ns,
        k8s_job_name=k8s_job_name,
        job_id=job_id,
        creator_id=creator_id,
        resolved_s3_datasets=s3_datasets_dict,
        resolved_fsx_mounts=resolved_fsx,
        run_as_group=run_as_group,
    )

    # 2. 下发 CR; 失败回滚 DDB 行 (参考推理: K8s 失败 → crud.delete)。
    try:
        await k8s.create_hyperpod_pytorch_job(k8s_ns, cr)
    except K8sAPIError as exc:
        try:
            await crud.delete(None, row)
        except Exception:
            logger.warning("training.create.rollback_fail", id=job_id)
        logger.warning(
            "training.create.k8s_fail",
            name=name,
            code=exc.code,
            msg=exc.message,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s create HyperPodPyTorchJob failed: {exc.message}",
        ) from exc

    logger.info(
        "training.create.ok",
        id=job_id,
        name=name,
        k8s_cr=k8s_job_name,
    )

    # 3. 存真实下发的 CR YAML 到 S3 (decision: ws 自己的桶). 失败不阻断.
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
    from app.modules.training.orchestration.lifecycle import audit_training
    await audit_training(row, current_user, "training.create")

    return row
