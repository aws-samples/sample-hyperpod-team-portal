"""Workspace 创建流 + 成员添加流 (DDB-only).

 决策固化: workspace 复用 HyperPod team API.

create_workspace_flow:
1. 校验 cluster + name/namespace 唯一
2. 调 AWS **CreateComputeQuota** (必须成功)
3. 写 DDB Workspaces 表; 失败 best-effort 删 AWS
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

import asyncio

from app.adapters.aws import eks_pod_identity
from app.adapters.aws import identitystore as idc_adapter
from app.adapters.aws.eks_pod_identity import EksPodIdentityAPIError
from app.adapters.aws.identitystore import IdcAPIError
from app.adapters.ddb import tables as ddb_tables
from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.cluster import crud as cluster_crud
from app.modules.workspace.api.schemas import (
    MemberAdd,
    MemberResponse,
    WorkspaceCreate,
)
from app.modules.workspace.domain.aws_team_mapping import (
    build_compute_quota_payload,
)
from app.modules.workspace.domain.namespace_spec import normalize_namespace
from app.modules.workspace.persistence import crud
from app.repositories import audit_log as audit_repo
from app.repositories import workspaces as ws_repo
from app.services.hyperpod_client import HyperPodAPIError, HyperPodClient

logger = get_logger(__name__)


async def _wait_namespace_ready(
    k8s: K8sClient, namespace: str, timeout_s: int = 30
) -> None:
    """轮询等 namespace 出现 (HyperPod taskgovernance reconcile 是异步的).

    通常 5-10s 内出现, 极端情况 20s+. 超时直接抛.
    """
    from kubernetes_asyncio import client as k8s_client_lib
    from kubernetes_asyncio.client.api_client import ApiClient
    from kubernetes_asyncio.client.exceptions import ApiException

    elapsed = 0
    interval = 2
    await k8s._load_config()
    while elapsed < timeout_s:
        async with ApiClient() as api:
            v1 = k8s_client_lib.CoreV1Api(api)
            try:
                await v1.read_namespace(name=namespace)
                logger.info(
                    "workspace.create.ns_ready",
                    ns=namespace,
                    waited_s=elapsed,
                )
                return
            except ApiException as exc:
                if exc.status != 404:
                    raise K8sAPIError(
                        f"ApiException.{exc.status}", exc.reason or str(exc)
                    ) from exc
        await asyncio.sleep(interval)
        elapsed += interval
    raise K8sAPIError(
        "NamespaceTimeout",
        f"namespace {namespace} not ready after {timeout_s}s "
        f"(HyperPod taskgovernance add-on may be slow)",
    )


# 开发机基础镜像来源: 两个系统内置 WorkspaceTemplate 的 defaultImage
# (开发机创建页"基础镜像"下拉即取自它们)。集群级 CR, 建 ws 时已存在。
_BASE_IMAGE_TEMPLATES: tuple[str, ...] = (
    "sagemaker-jupyter-template",
    "sagemaker-code-editor-template",
)


async def _seed_base_images(
    k8s: K8sClient, workspace_id: str, creator_username: str
) -> None:
    """建 ws 后把开发机基础镜像注册进镜像中心 (best-effort)。

    基础镜像来源与开发机创建页"基础镜像"下拉一致 = 两个系统模板的 allowedImages
    (通常 CPU 版 + GPU 版)。取两模板 allowedImages 并集; seed_images 按 URI 去重。
    """
    from app.modules.registry.orchestration import images as image_orch

    try:
        templates = await k8s.list_workspace_templates()
        by_name = {
            (t.get("metadata") or {}).get("name"): t for t in templates
        }
        pairs: list[tuple[str, str]] = []
        for tpl_name in _BASE_IMAGE_TEMPLATES:
            spec = (by_name.get(tpl_name) or {}).get("spec") or {}
            for uri in spec.get("allowedImages") or []:
                if uri:
                    # allowedImages 只有 URI, 无 per-image 名; 用 URI 末段兜底 (seed_images 内)
                    pairs.append((uri, ""))
        n = await image_orch.seed_images(workspace_id, pairs, creator_username)
        logger.info("workspace.create.seed_images", ws_id=workspace_id, n=n)
    except Exception as exc:  # noqa: BLE001 - 镜像 seed 失败不影响 ws 创建
        logger.warning(
            "workspace.create.seed_images_fail",
            ws_id=workspace_id,
            err=str(exc),
        )


async def _seed_resource_templates(workspace_id: str) -> None:
    """建 ws 后按创建者(请求)语言预置默认资源模板 (best-effort)。

    名称/描述落库后不随语言切换, 故在建 ws 这一刻按创建者语言写入;
    失败只 warn, 不影响 ws 创建 (list 端点的懒加载 ensure_seeded 仍作兜底)。
    """
    # 懒 import: 避免与 resource_templates (其 service 依赖 workspace.persistence) 循环
    from app.modules.resource_templates import ensure_seeded

    try:
        await ensure_seeded(workspace_id)
    except Exception as exc:  # noqa: BLE001 - 模板 seed 失败不影响 ws 创建
        logger.warning(
            "workspace.create.seed_resource_templates_fail",
            ws_id=workspace_id,
            err=str(exc),
        )


# ===== Workspace =====

async def create_workspace_flow(
    db: Any,
    payload: WorkspaceCreate,
    current_user: dict[str, Any],
    hp_client: HyperPodClient,
    k8s_client: K8sClient | None = None,
) -> dict[str, Any]:
    """创建事务 (DDB-only).

    1. 校验 cluster (走 AWS DescribeCluster)
    2. 校验 name/namespace 唯一 (DDB scan)
    3. 调 AWS CreateComputeQuota → AWS 自动建 namespace + Kueue queue
    4. 在 ns 里建 SA + Role + RoleBinding + EKS PodIdentityAssociation
    5. 写 DDB Workspaces; 失败 best-effort 删 AWS
    """
    del db
    cluster = await cluster_crud.get_cluster_by_id(None, payload.cluster_id)
    if cluster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"cluster not found: {payload.cluster_id}",
        )
    if not cluster.get("hyperpod_cluster_arn"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"cluster '{cluster.get('cluster_tag')}' has no "
                "hyperpod_cluster_arn, cannot create AWS ComputeQuota"
            ),
        )

    # name 唯一 (DDB scan)
    existing = await crud.get_workspace_by_name(
        None, cluster.get("id"), payload.name
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"workspace name '{payload.name}' already exists",
        )

    namespace = normalize_namespace(payload.namespace, default_from_name=payload.name)

    ns_existing = await crud.get_workspace_by_namespace(
        None, cluster.get("id"), namespace
    )
    if ns_existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"namespace '{namespace}' already used",
        )

    # AWS CreateComputeQuota
    aws_payload = build_compute_quota_payload(
        name=payload.name,
        cluster_arn=cluster["hyperpod_cluster_arn"],
        resources=[r.model_dump() for r in payload.resources],  # type: ignore[misc]
        sharing_strategy=payload.sharing_strategy,
        preempt_team_tasks=payload.preempt_team_tasks,
        fair_share_weight=payload.fair_share_weight,
        description=payload.description,
    )
    try:
        aws_resp = await hp_client.create_compute_quota(aws_payload)
    except HyperPodAPIError as exc:
        logger.warning(
            "workspace.create.aws_quota_fail",
            name=payload.name,
            code=exc.code,
            msg=exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS CreateComputeQuota failed [{exc.code}]: {exc.message}",
        ) from exc

    compute_quota_id = aws_resp["ComputeQuotaId"]
    compute_quota_arn = aws_resp["ComputeQuotaArn"]

    # ===== 步骤 4: K8s 配套资源 (SA + Role + RoleBinding + Pod Identity) =====
    # HyperPod taskgovernance add-on 异步 reconcile 出 namespace, 这里 retry 等 ns 出现
    # 失败时反向回滚 (删 AWS quota), 抛 502
    settings = get_settings()
    k8s_client_local = k8s_client or K8sClient(
        context=settings.kube_context or None  # None = 用 kubeconfig 当前 context
    )
    pod_identity_assoc_id: str | None = None
    try:
        # 等 namespace 出现 (最多 30s · taskgovernance reconcile 通常 5-10s)
        await _wait_namespace_ready(k8s_client_local, namespace, timeout_s=30)

        # 建 ServiceAccount (幂等)
        await k8s_client_local.create_workspace_service_account(
            namespace=namespace, workspace_name=payload.name
        )

        # 建 Role + RoleBinding (幂等)
        await k8s_client_local.create_workspace_role_and_binding(
            namespace=namespace, workspace_name=payload.name
        )

        # 关联 Pod Identity (SA → platform-pod-role)
        if not settings.platform_pod_role_arn or not settings.eks_cluster_name:
            logger.warning(
                "workspace.create.pod_identity_skipped",
                reason="platform_pod_role_arn or eks_cluster_name not configured",
                ns=namespace,
            )
        else:
            try:
                assoc = await eks_pod_identity.create_association(
                    cluster_name=settings.eks_cluster_name,
                    namespace=namespace,
                    service_account="workspace-default",
                    role_arn=settings.platform_pod_role_arn,
                )
                pod_identity_assoc_id = assoc["association_id"]
            except EksPodIdentityAPIError as exc:
                # ResourceInUseException = 已存在 (幂等), 视为成功
                if "InUse" in exc.code or "AlreadyExists" in exc.code:
                    logger.info(
                        "workspace.create.pod_identity.exists",
                        ns=namespace,
                    )
                else:
                    raise
    except (K8sAPIError, EksPodIdentityAPIError) as exc:
        logger.error(
            "workspace.create.k8s_setup_fail_rolling_back_aws",
            name=payload.name,
            quota_id=compute_quota_id,
            err=str(exc),
        )
        # 反向回滚: 删可能已建的 K8s 资源 + 删 AWS quota
        try:
            await k8s_client_local.delete_workspace_role_and_binding(namespace)
        except Exception:
            pass
        try:
            await k8s_client_local.delete_workspace_service_account(namespace)
        except Exception:
            pass
        try:
            await hp_client.delete_compute_quota(compute_quota_id)
        except Exception as rb_exc:
            logger.error(
                "workspace.create.aws_rollback_fail",
                err=str(rb_exc),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"K8s setup failed (AWS rolled back): {exc}",
        ) from exc

    # 写 DDB. 失败 best-effort 删 AWS + K8s.
    owner_id = str(current_user.get("user_id") or current_user.get("id"))
    try:
        item = await ws_repo.create_workspace(
            cluster_arn=cluster["hyperpod_cluster_arn"],
            name=payload.name,
            display_name=payload.display_name,
            namespace=namespace,
            owner_user_id=owner_id,
            compute_quota_id=compute_quota_id,
            description=payload.description,
            metadata={
                "name": payload.name,
                "namespace": namespace,
                "compute_quota_arn": compute_quota_arn,
                "cluster_id": str(cluster.get("id") or ""),
                "pod_identity_association_id": pod_identity_assoc_id or "",
                "fsx_mounts": [],  # 初始空, 后续 attach 加进来
            },
        )
    except Exception as exc:
        logger.error(
            "workspace.create.ddb_fail_rolling_back",
            name=payload.name,
            quota_id=compute_quota_id,
            err=str(exc),
        )
        # 级联清: Pod Identity Association → K8s Role/RoleBinding/SA → AWS quota
        if pod_identity_assoc_id:
            try:
                await eks_pod_identity.delete_association(
                    cluster_name=settings.eks_cluster_name,
                    association_id=pod_identity_assoc_id,
                )
            except Exception:
                pass
        try:
            await k8s_client_local.delete_workspace_role_and_binding(namespace)
        except Exception:
            pass
        try:
            await k8s_client_local.delete_workspace_service_account(namespace)
        except Exception:
            pass
        try:
            await hp_client.delete_compute_quota(compute_quota_id)
        except HyperPodAPIError as rollback_exc:
            logger.error(
                "workspace.create.aws_rollback_fail",
                name=payload.name,
                code=rollback_exc.code,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DDB write failed after AWS create (rolled back): {exc}",
        ) from exc

    item["id"] = item["workspace_id"]
    item["sagemaker_compute_quota_id"] = compute_quota_id
    item["sagemaker_compute_quota_arn"] = compute_quota_arn
    item["name"] = payload.name
    item["namespace"] = namespace
    item["status"] = "active"
    item["cluster_id"] = str(cluster.get("id") or "")

    logger.info(
        "workspace.create.ok",
        ws_id=item["workspace_id"],
        name=payload.name,
        namespace=namespace,
        cluster=cluster.get("cluster_tag"),
        quota_id=compute_quota_id,
        actor=current_user.get("username"),
    )

    # 自动把开发机基础镜像 (两个系统 WorkspaceTemplate 的 defaultImage) 注册进镜像中心,
    # 新 ws 开箱即有可用镜像。best-effort: 失败只 warn, 不回滚已建好的 ws。
    seed_actor = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    await _seed_base_images(k8s_client_local, item["workspace_id"], seed_actor)

    # 预置默认资源模板 (按创建者请求语言生成名称/描述), best-effort 同上。
    await _seed_resource_templates(item["workspace_id"])

    # AuditLog · append-only (创建/删除写 audit)
    # 写失败不影响主流程 (业务已成功; 审计是事后追溯)
    actor_username = str(
        current_user.get("username") or current_user.get("user_id") or ""
    )
    try:
        await audit_repo.append(
            scope_key=ddb_tables.scope_key_workspace(item["workspace_id"]),
            actor_user_id=actor_username,
            actor_role="platform-admin",
            operation="workspace.create",
            target_type="workspace",
            target_id=item["workspace_id"],
            status="succeeded",
            metadata={
                "name": payload.name,
                "namespace": namespace,
                "cluster_arn": cluster["hyperpod_cluster_arn"],
                "compute_quota_id": compute_quota_id,
                "actor_email": current_user.get("email") or "",
                "actor_display_name": current_user.get("display_name") or "",
            },
        )
    except Exception as audit_exc:  # pragma: no cover - 审计失败不影响主流程
        logger.warning(
            "workspace.create.audit_fail",
            ws_id=item["workspace_id"],
            err=str(audit_exc),
        )

    return item


# ===== Member =====

async def add_member_flow(
    db: Any,
    ws_id: Any,
    payload: MemberAdd,
    current_user: dict[str, Any],
) -> MemberResponse:
    """加成员到 workspace.

    PR feat/idc-user-search, 2026-05-26:
        - payload.user_id 语义 = IdC username (前端 IdC 搜索框选完后传过来)
        - 调 IdC find_user 拿真 email + display_name 写 DDB
        - IdC 找不到该 username 抛 404 (admin 输错 username 防呆)
        - 失败时抛 502 (IdC API 故障)
    """
    del db
    ws = await crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}")

    # 调 IdC 拿真 email + display_name (前端 Modal 已经搜过, 这里是双重保险 +
    # 拿到完整字段写 DDB 冗余字段)
    member_username = str(payload.user_id)
    try:
        idc_user = await idc_adapter.find_user(member_username)
    except IdcAPIError as exc:
        logger.warning(
            "workspace.member.add.idc_fail",
            ws_id=str(ws_id), username=member_username, err=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"IdC API failed [{exc.code}]: {exc.message}",
        ) from exc
    if idc_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IdC user not found: {member_username}",
        )

    member_email = idc_user.get("email") or member_username
    member_display_name = idc_user.get("display_name") or member_username

    membership = await crud.add_membership(
        None,
        ws_id=ws_id,
        user_id=member_username,  # 实际语义 = username
        role=payload.role,
        email=member_email,
        display_name=member_display_name,
        invited_by=current_user.get("username") or current_user.get("user_id") or "",
    )
    return MemberResponse(
        user_id=member_username,
        email=member_email,
        display_name=member_display_name,
        role=membership["role"],  # type: ignore[arg-type]
        joined_at=membership.get("joined_at") or "",
    )
