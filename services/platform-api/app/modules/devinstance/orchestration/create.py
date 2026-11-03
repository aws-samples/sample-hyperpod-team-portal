"""DevInstance 创建流程 (DDB-only).

K8s Workspace CR 是 SoT; DDB ResourceIndex 写索引.
失败时 best-effort 回滚 ResourceIndex.
"""

from __future__ import annotations

import asyncio
from typing import Any

import yaml
from fastapi import HTTPException, status

from app.adapters.k8s import K8sAPIError, K8sClient
from app.adapters.k8s.workspace_resources import SA_NAME as WORKSPACE_SA_NAME
from app.core.config import get_settings
from app.core.i18n import t
from app.core.labels import sanitize_label_value
from app.core.priority_defaults import default_priority_class
from app.core.logging import get_logger
from app.core.naming import make_dns_name
from app.modules.quota.orchestration.workspace_quota import get_workspace_quota
from app.modules.workspace import crud as ws_crud

from ..api.schemas import DevInstanceCreate
from ..domain.cr import render_workspace_cr
from ..persistence import crud
from .mounts import resolve_mounts
from .ssm_register import register_ssm_in_sidecar

logger = get_logger(__name__)


async def _assert_instance_type_allowed(
    hp: Any, ws_id: Any, instance_type: str
) -> None:
    """校验 instance_type ∈ ws ComputeQuota 已分配机型, 不在 → 403。

    安全 (API 已公网): 机型只能选 ws 配额里真实分配的, 不能自由填 (防越权
    用未授权/集群没有的机型)。参照推理 inference._assert_instance_type_allowed。
    """
    quota = await get_workspace_quota(None, hp, ws_id)
    allowed = {r.instance_type for r in (quota.resources or [])}
    if instance_type not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t(
                "devinstance.instance_type_not_allowed",
                instance_type=instance_type,
                allowed=sorted(allowed) or t("devinstance.allowed_none"),
            ),
        )


_FALLBACK_K8S_NS = "default"


async def _resolve_cpu_instance_groups() -> list[str]:
    """实时列集群 IG, 按机型 GPU 数筛出 CPU IG (GPU=0) 的 InstanceGroupName。

    用于 CPU 开发机的 nodeAffinity 软优先。describe-cluster 实时拿 IG 列表
    (含 InstanceType), EC2 DescribeInstanceTypes 查每机型 GPU 数。
    任意环节失败 → 返空 (不加软优先, 降级到仅 health required, 安全方向)。
    """
    from app.adapters.aws import cluster_describe
    from app.adapters.aws.ec2_instance_types import get_gpu_count

    try:
        igs = await cluster_describe.list_instance_groups()
    except Exception as exc:  # noqa: BLE001
        logger.warning("dev_instance.cpu_ig.list_fail", err=str(exc))
        return []

    cpu_igs: list[str] = []
    for ig in igs:
        name = ig.get("InstanceGroupName")
        itype = ig.get("InstanceType")
        if not name or not itype:
            continue
        if await get_gpu_count(itype) == 0:
            cpu_igs.append(name)
    return cpu_igs


async def create_dev_instance_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    ws_id: Any,
    payload: DevInstanceCreate,
    current_user: dict[str, Any],
) -> dict[str, Any]:
    del db
    # 1. workspace 存在
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )

    # 2. 不再做 name 唯一性检查 (与训练任务一致): K8s CR 名 = sanitize(名)+10随机后缀,
    #    k8s 层天然唯一不撞; DDB 行用各自 uuid 主键, 同名仅是展示名重复, 允许。
    #    (用户体验: 删了再用同名 / 多个同名开发机都不再被 409 挡。)

    # 3. template 解析
    try:
        tpl = await k8s.get_workspace_template(payload.template_name)
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"template '{payload.template_name}' not found: {exc.message}",
        ) from exc
    tpl_spec = tpl.get("spec") or {}
    default_image = tpl_spec.get("defaultImage")
    allowed_images = tpl_spec.get("allowedImages") or []
    allow_custom_images = bool(tpl_spec.get("allowCustomImages", False))
    image = payload.image or default_image
    # allowCustomImages=true 时模板允许任意镜像 (BYOI, 用户从 ECR 选自定义镜像),
    # 不强制 image ∈ allowedImages; 与 WorkspaceTemplate CRD 字段语义一致.
    if not allow_custom_images and image not in allowed_images:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"image '{image}' not in template allowedImages: {allowed_images}",
        )
    app_type = tpl_spec.get("appType") or "jupyterlab"

    # 3.4 机型约束: pool (资源池, 新) 优先于 instance_type (单机型, 兼容)。
    # pool → 复用 quota.list_workspace_pool_instance_types 拿该池所有机型 (后端
    # EC2 GpuInfo 权威判, 三模块同源); 空 → 400 (该池无可用机型)。
    pool_instance_types: list[str] = []
    if payload.pool:
        from app.modules.quota.orchestration.workspace_quota import (
            list_workspace_pool_instance_types,
        )

        pool_instance_types = await list_workspace_pool_instance_types(
            None, hp, ws_id, payload.pool
        )
        if not pool_instance_types:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                t("devinstance.pool_no_instance_types", pool=payload.pool),
            )
    elif payload.instance_type:
        await _assert_instance_type_allowed(hp, ws_id, payload.instance_type)

    # 4. 准备 K8s 字段
    # CR 名 = sanitize(用户名)[截断52] + '-' + 10 位随机 (a-z0-9), 与训练任务同源
    # (app.core.naming.make_dns_name): 保证 K8s 资源名唯一、不撞名。DDB 仍存用户输入的
    # payload.name (列表/详情展示干净名); 此 k8s_ws_name 存 k8s_name 字段供详情页"K8s Workspace"显示。
    k8s_ws_name = make_dns_name(payload.name, fallback="dev")
    k8s_ns = (
        ws.get("namespace")
        or (ws.get("metadata_json") or {}).get("namespace")
        or _FALLBACK_K8S_NS
    )
    # 校验勾选挂载 (授权 + PVC 存在) + 算 gid, 与改规格共用同一判定。
    creator_username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    volume_mounts_json, ws_primary_gid, supplemental_gids = await resolve_mounts(
        k8s,
        ws_id=ws_id,
        k8s_ns=k8s_ns,
        username=creator_username,
        ws_md=ws.get("metadata_json") or {},
        volume_mounts=payload.volume_mounts,
    )

    creator_id = str(current_user.get("user_id") or current_user.get("id"))
    priority_class = default_priority_class("devinstance")

    # 5. 写 DDB ResourceIndex (失败抛 502)
    row = await crud.create(
        None,
        workspace_id=ws_id,
        creator_user_id=creator_id,
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        k8s_namespace=k8s_ns,
        k8s_workspace_name=k8s_ws_name,
        template_name=payload.template_name,
        app_type=app_type,
        image=image,
        cpu_request_millicores=payload.cpu_request_millicores,
        memory_request_mib=payload.memory_request_mib,
        gpu_count=payload.gpu_count,
        efa_count=payload.efa_count,
        storage_size_gib=payload.storage_size_gib,
        env_json=payload.env or {},
        priority_class=priority_class,
        metadata_json={
            "volume_mounts": volume_mounts_json,
            "instance_type": payload.instance_type,
            "pool": payload.pool,
        },
    )

    # 6. 构造 Workspace CR
    kueue_queue_name = f"{k8s_ns}-localqueue"
    # creator_id 可能是邮箱格式 username (含 @), 作为 K8s label value 必须合法化
    # (label value 只准 [A-Za-z0-9._-], 否则 CR apply 422)。
    cr_labels = {
        "platform.hyperpod.io/workspace-id": str(ws_id),
        "platform.hyperpod.io/creator-id": sanitize_label_value(creator_id, fallback="unknown"),
        "platform.hyperpod.io/dev-instance-id": str(row["id"]),
    }
    # JupyterLab 经平台 proxy 子路径访问时, 必须知道自己的 base_url, 否则
    # config 里 20+ 个 *Url 字段 (settingsUrl/themesUrl/labextensionsUrl 等)
    # 用绝对路径 /lab/... → 浏览器请求不走 proxy → 白屏。SMD jupyterlab
    # entrypoint 读 WORKSPACE_BASE_URL → --ServerApp.base_url, 让所有 URL
    # 从源头带 proxy 前缀。code-editor 容忍子路径, 不需要。
    cr_env = dict(payload.env or {})
    if app_type == "jupyterlab":
        cr_env["WORKSPACE_BASE_URL"] = f"/api/v1/dev-instances/{row['id']}/proxy/"

    # CPU 开发机 (gpu_count==0): 软优先调度到 CPU instance group, 不占 GPU 节点。
    # 实时查集群 IG + EC2 机型 GPU 数筛出 CPU IG (失败返空, 降级仅 health required)。
    # GPU 开发机不处理 (GPU 资源请求会自然落 GPU 节点)。
    preferred_igs: list[str] = []
    if not payload.gpu_count:
        preferred_igs = await _resolve_cpu_instance_groups()

    cr = render_workspace_cr(
        name=k8s_ws_name,
        namespace=k8s_ns,
        display_name=payload.display_name,
        template_name=payload.template_name,
        app_type=app_type,
        image=image,
        cpu_millicores=payload.cpu_request_millicores,
        memory_mib=payload.memory_request_mib,
        gpu_count=payload.gpu_count,
        efa_count=payload.efa_count,
        storage_size_gib=payload.storage_size_gib,
        env=cr_env,
        # volume_mounts_json 不含 sub_path: 子目录隔离已在 PV 层 (FSx mountname 拼
        # subdir) 完成, 跟 S3 用 prefix 在 PV 层圈定一致. Spaces operator 0.0.16 的
        # Workspace CRD spec.volumes[] 也不认 subPath, 传了会被 prune.
        volume_mounts=volume_mounts_json,
        labels=cr_labels,
        kueue_queue_name=kueue_queue_name,
        priority_class=priority_class,
        primary_gid=ws_primary_gid,
        supplemental_gids=supplemental_gids,
        # 用 workspace-default SA (已 Pod Identity 关联 platform-pod-role),
        # 让开发机 pod 能访问 AWS 资源 (权限由 platform-pod-role IAM policy 控)
        service_account_name=WORKSPACE_SA_NAME,
        preferred_instance_groups=preferred_igs,
        instance_type=payload.instance_type,
        instance_types=pool_instance_types or None,
    )

    # 调试用: 创建前 dump CR yaml (开发期联调看 spec.volumes / labels 拼对没)
    try:
        logger.info(
            "dev_instance.create.cr_yaml",
            id=str(row["id"]),
            yaml=yaml.safe_dump(cr, allow_unicode=True, sort_keys=False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "dev_instance.create.cr_repr",
            id=str(row["id"]),
            err=str(exc),
            repr=repr(cr)[:2000],
        )

    # 7. K8s 创建 (失败回滚 DDB)
    try:
        await k8s.create_workspace(k8s_ns, cr)
    except K8sAPIError as exc:
        try:
            await crud.delete(None, row)
        except Exception:
            pass  # best-effort
        logger.warning(
            "dev_instance.create.k8s_fail",
            name=payload.name,
            ws_id=str(ws_id),
            code=exc.code,
            msg=exc.message,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s create failed: {exc.message}",
        ) from exc

    logger.info(
        "dev_instance.create.ok",
        id=row["id"],
        name=row["name"],
        ws_id=str(ws_id),
        k8s_name=k8s_ws_name,
    )

    from .lifecycle import audit_devinstance
    await audit_devinstance(row, current_user, "devinstance.create")

    # 8. 平台已切 directSSH: 连接靠 addon 建的固定 DNS + sshd:22222, 无需平台
    # 侧做任何注册 (旧 SSM sidecar 注册流已停)。开发机起来后 addon 自动建
    # ssh-<name> Service + external-dns 同步 DNS, access-info 端点即时读回。
    return row


# 防止 fire-and-forget asyncio.create_task 被 GC 吞掉异常的 strong-ref set
_BG_TASKS: set[asyncio.Task[Any]] = set()


# 已停用: 平台切 directSSH 后不再做 SSM 注册, 创建流不再调用此函数 (待清理)。
async def _post_create_ssm_init(
    k8s: K8sClient, instance: dict[str, Any]
) -> None:
    """后台 SSM 初始化任务 · 创建流派出, 不阻塞 HTTP 响应.

    成功: 写 ssm_managed_id + ssm_init_status='done'
    失败: 写 ssm_init_status='failed' (用户可在 UI 手动重试 /remote-access)
    """
    inst_id = str(instance.get("id") or "")
    try:
        # 标记 registering · 让前端能显示 "正在初始化 SSM..."
        await crud.update(
            None,
            {**instance, "ssm_init_status": "registering"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("ssm_init.mark_registering_fail", id=inst_id, err=str(exc))

    try:
        mi = await register_ssm_in_sidecar(k8s, instance)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ssm_init.unexpected", id=inst_id, err=str(exc))
        mi = None

    # 重新拉一次 instance, 用户可能此期间改了名等 (虽然几率小)
    try:
        latest = await crud.get(None, inst_id) or instance
    except Exception:  # noqa: BLE001
        latest = instance

    if mi:
        latest["ssm_managed_id"] = mi
        latest["ssm_init_status"] = "done"
    else:
        latest["ssm_init_status"] = "failed"

    try:
        await crud.update(None, latest)
        logger.info(
            "ssm_init.complete",
            id=inst_id,
            mi=mi,
            status=latest["ssm_init_status"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ssm_init.write_fail", id=inst_id, err=str(exc))
