"""Cluster 模块 HTTP 路由 (DDB-only).

数据 100% 来自 AWS DescribeCluster / ListClusterNodes (TTL 缓存),
不再有 RDS 落地. db 参数从 router 移除.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.adapters.aws import cluster_describe, compute_quota, nodes
from app.adapters.aws.ec2_instance_types import get_instance_specs
from app.adapters.k8s import K8sClient
from app.core.config import get_settings
from app.core.security import require_admin
from app.modules.cluster.api.deps import get_hyperpod_client, get_k8s_client
from app.modules.cluster.api.schemas import ClusterSummary
from app.modules.cluster.orchestration.get_summary import get_cluster_summary
from app.modules.cluster.orchestration.sync_cluster import sync_cluster
from app.modules.cluster.persistence import crud
from app.services.hyperpod_client import HyperPodClient


def _resolve_cluster_name(cluster_tag: str) -> str:
    """cluster_tag 等于 ClusterName; 但平台只有 1 个 cluster, 兜底 settings."""
    if cluster_tag and cluster_tag != "default":
        return cluster_tag
    return get_settings().hyperpod_cluster_name

cluster_router = APIRouter(tags=["clusters"])


@cluster_router.get(
    "",
    response_model=list[ClusterSummary],
    summary="列出集群 (M1 单集群, 至多 1 条)",
    description=(
        "**只读元数据**, 前端顶栏用来切集群上下文.\n\n"
        "**M1 单集群实现**: 只返回 `settings.hyperpod_cluster_name` 指向的那一个集群, "
        "拿不到 (AWS 报错) 时返回空数组. 尚未支持多集群 / 普通 EKS / EAS 纳管.\n\n"
        "`?type=hyperpod|eks|eas-inference` 过滤是对这唯一一条做匹配, "
        "不匹配就返回空数组.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DescribeCluster` 实时拉取 (无 DDB clusters 表)."
    ),
    responses={403: {"description": "非平台超管"}},
)
async def list_clusters_endpoint(
    type_filter: str | None = Query(
        default=None,
        alias="type",
        description="过滤 cluster 类型: hyperpod / eks / eas-inference",
    ),
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[ClusterSummary]:
    rows = await crud.list_clusters(None, type_filter=type_filter)
    return [ClusterSummary.model_validate(c) for c in rows]


@cluster_router.get(
    "/{cluster_tag}",
    response_model=ClusterSummary,
    summary="按 tag 查询集群",
    description=(
        "按 `cluster_tag` (= ClusterName) 精确查询单个集群的元数据. "
        "前端切集群下钻查详情时使用.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DescribeCluster` 实时拉取 (无 DDB clusters 表). "
        "拉取过程中任何异常都被吞掉当作『查不到』→ 404, 因此 404 也可能是 AWS 侧故障."
    ),
    responses={
        403: {"description": "非平台超管"},
        404: {"description": "Cluster 不存在, 或 SageMaker 调用失败 (异常被吞)"},
    },
)
async def get_cluster_endpoint(
    cluster_tag: str,
    _admin: dict[str, Any] = Depends(require_admin),
) -> ClusterSummary:
    cluster = await crud.get_cluster_by_tag(None, cluster_tag)
    if cluster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cluster not found: {cluster_tag}",
        )
    return ClusterSummary.model_validate(cluster)


@cluster_router.post(
    "/{cluster_tag}/sync",
    summary="从 AWS + K8s 拉最新集群快照",
    description=(
        "手动触发一次集群快照同步: 汇聚 SageMaker `DescribeCluster` + "
        "`ListClusterNodes` + K8s `Node` 列表, 组装成前端可用的健康报表.\n\n"
        "**不落 DB** (DDB-only): 只返回本次拉到的实时视图, 不写回 `clusters` 表.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker HyperPod API + K8s API-Server."
    ),
    responses={
        403: {"description": "非平台超管"},
        404: {"description": "Cluster 不存在"},
    },
)
async def sync_cluster_endpoint(
    cluster_tag: str,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    k8s: K8sClient = Depends(get_k8s_client),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return await sync_cluster(
            db=None, cluster_tag=cluster_tag, hp_client=hp, k8s_client=k8s
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@cluster_router.get(
    "/{cluster_tag}/summary",
    summary="集群综合概览",
    description=(
        "返回单集群的**综合概览**: 实例组配置 + 节点状态汇总 + 该集群下所有 "
        "ComputeQuota 分配情况, 供平台管理页顶部大卡片使用.\n\n"
        "**注意 quotas 字段是全集群口径**: 底层按 quota 列表拉取时**忽略 cluster scope**, "
        "即返回该 AWS 账号/区域下所有 ComputeQuota, 不按本 cluster 过滤; "
        "且会对每条 quota 再发一次 `DescribeComputeQuota` (N+1 调用).\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DescribeCluster` + `ListClusterNodes` (实时, 底层 TTL 缓存) + "
        "`ListComputeQuotas` + 逐条 `DescribeComputeQuota`, 应用侧合并. "
        "GPU 用量类字段目前是降级口径 (`gpus_total/gpus_used/pending` 恒 0, 待 M2 K8s 集成)."
    ),
    responses={
        403: {"description": "非平台超管"},
        404: {"description": "Cluster 不存在, 或 SageMaker DescribeCluster 失败 (异常被吞)"},
    },
)
async def get_cluster_summary_endpoint(
    cluster_tag: str,
    hp_client: HyperPodClient = Depends(get_hyperpod_client),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    payload = await get_cluster_summary(
        db=None, cluster_tag=cluster_tag, hp_client=hp_client
    )
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cluster not found: {cluster_tag}",
        )
    return payload


# ===== Admin endpoints (live AWS, 30s TTL) =====


async def _enrich_instance_groups_with_specs(
    cluster_name: str | None,
) -> list[dict[str, Any]]:
    """列 InstanceGroups 并给每项附加机型规格 (gpu_count/gpu_spec/gpu_type/
    vcpu/memory_gib), 规格走 us-east-1 EC2 (见 ec2_instance_types)。查不到的机型
    附加 0/None (degrade)。

    注: list_instance_groups 返回的 dict 来自 describe_cluster 的 TTL 缓存, 故这里
    浅拷贝每项再附加派生字段, 不污染缓存对象。
    """
    igs = await cluster_describe.list_instance_groups(cluster_name)
    types = [ig.get("InstanceType") for ig in igs if ig.get("InstanceType")]
    specs = await get_instance_specs(list(dict.fromkeys(types)))
    out: list[dict[str, Any]] = []
    for ig in igs:
        spec = specs.get(ig.get("InstanceType"))
        out.append({
            **ig,
            "gpu_count": spec.gpu_count if spec else 0,
            "gpu_spec": spec.gpu_spec if spec else None,
            "gpu_type": spec.gpu_type if spec else None,
            "vcpu": spec.vcpu if spec else 0,
            "memory_gib": spec.memory_gib if spec else 0.0,
        })
    return out


@cluster_router.get(
    "/{cluster_tag}/instance-groups",
    summary="列出集群实例组 + 每机型规格 (实时)",
    description=(
        "列出该 HyperPod 集群下所有 InstanceGroup 及其配置 "
        "(实例类型 / 目标台数 / 生命周期脚本 / 训练计划等), 并**逐项回填机型规格** "
        "`gpu_count / gpu_spec / gpu_type / vcpu / memory_gib` (走 us-east-1 EC2 `DescribeInstanceTypes`).\n\n"
        "**为何要回填**: 前端配额页 / Dashboard 判池/型号/加速卡数不再依赖静态表 "
        "(`instance-types.ts` 已删), 后端为唯一权威源.\n\n"
        "**降级**: EC2 查不到的机型规格字段返 `0/None`, 不影响主字段.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DescribeCluster` + EC2 `DescribeInstanceTypes` (均 TTL 缓存)."
    ),
    responses={403: {"description": "非平台超管"}},
)
async def list_instance_groups_endpoint(
    cluster_tag: str,
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[dict[str, Any]]:
    name = _resolve_cluster_name(cluster_tag)
    return await _enrich_instance_groups_with_specs(name)


@cluster_router.get(
    "/{cluster_tag}/nodes",
    summary="列出集群节点 (实时)",
    description=(
        "列出该集群所有实例节点的关键状态字段 "
        "(instance_id / group / type / AZ / status / status_message / created_at), "
        "并附总数 + 健康数 (`status=Running`) 汇总. 平台节点健康页使用.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `ListClusterNodes` (实时, 30s TTL 缓存)."
    ),
    responses={403: {"description": "非平台超管"}},
)
async def list_cluster_nodes_endpoint(
    cluster_tag: str,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    name = _resolve_cluster_name(cluster_tag)
    items = await nodes.list_cluster_nodes(name)
    out: list[dict[str, Any]] = []
    for n in items:
        creation = n.get("LastSoftwareUpdateTime") or n.get("LaunchTime")
        out.append({
            "instance_id": n.get("InstanceId"),
            "instance_group_name": n.get("InstanceGroupName"),
            "instance_type": n.get("InstanceType"),
            "az": (n.get("Placement") or {}).get("AvailabilityZone"),
            "status": (n.get("InstanceStatus") or {}).get("Status"),
            "status_message": (n.get("InstanceStatus") or {}).get("Message"),
            "created_at": creation.isoformat() if hasattr(creation, "isoformat") else creation,
        })
    return {
        "total": len(out),
        "healthy": sum(1 for x in out if x["status"] == "Running"),
        "items": out,
    }


@cluster_router.get(
    "/{cluster_tag}/nodes/{instance_id}",
    summary="查询单个节点详情 (实时)",
    description=(
        "按 `instance_id` 查询单个节点的完整详情, "
        "含实例元数据 / 生命周期脚本执行结果 / 最近一次软件更新时间. "
        "节点健康页下钻使用.\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DescribeClusterNode` (实时).\n\n"
        "**注意**: 节点不存在 / instance_id 无效时 SageMaker 报错会直接冒出 → **500**, "
        "不会返回 404 (本服务未注册异常 handler)."
    ),
    responses={
        403: {"description": "非平台超管"},
        500: {"description": "节点不存在 / instance_id 无效 / SageMaker 调用失败"},
    },
)
async def describe_cluster_node_endpoint(
    cluster_tag: str,
    instance_id: str,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    name = _resolve_cluster_name(cluster_tag)
    # adapter 签名是 describe_cluster_node(node_id, cluster_name=None); 别传反
    return await nodes.describe_cluster_node(instance_id, name)


def _to_iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _quota_summary_to_camel(s: dict[str, Any]) -> dict[str, Any]:
    """boto3 ComputeQuotaSummary (PascalCase) → 前端 ComputeQuota (camelCase)."""
    config = s.get("ComputeQuotaConfig") or {}
    target = s.get("ComputeQuotaTarget") or {}
    resources = []
    for r in config.get("ComputeQuotaResources") or []:
        resources.append({
            "instanceType": r.get("InstanceType"),
            "count": r.get("Count"),
            "accelerators": r.get("Accelerators"),
            "vCpu": r.get("VCpu"),
            "memoryInGiB": r.get("MemoryInGiB"),
        })
    sharing = config.get("ResourceSharingConfig") or {}
    return {
        "computeQuotaArn": s.get("ComputeQuotaArn"),
        "computeQuotaId": s.get("ComputeQuotaId"),
        "name": s.get("Name"),
        "description": s.get("Description"),
        "clusterArn": s.get("ClusterArn"),
        "activationState": s.get("ActivationState"),
        "status": s.get("Status"),
        "computeQuotaVersion": s.get("ComputeQuotaVersion"),
        "resources": resources,
        "sharingConfig": {
            "strategy": sharing.get("Strategy"),
            "borrowLimit": sharing.get("BorrowLimit"),
        },
        "preemptTeamTasks": config.get("PreemptTeamTasks"),
        "target": {
            "teamName": target.get("TeamName"),
            "fairShareWeight": target.get("FairShareWeight"),
        },
        "creationTime": _to_iso(s.get("CreationTime")),
        "lastModifiedTime": _to_iso(s.get("LastModifiedTime")),
    }


@cluster_router.get(
    "/{cluster_tag}/quotas",
    summary="列出集群下所有 ComputeQuota (实时)",
    description=(
        "列出该集群下所有 SageMaker HyperPod ComputeQuota (PascalCase 字段已转 camelCase 交前端). "
        "返回 shape: `{clusterArn, clusterTag, quotas[ComputeQuota]}`. "
        "平台配额总览页使用, 便于对比多 ws 分配情况.\n\n"
        "每条 quota 的 `resources[]` 项为 `{instanceType, count, accelerators, vCpu, memoryInGiB}`, "
        "**原样透传 SageMaker 返回值, 不做 EC2 机型规格回填** — SageMaker 侧没填的项就是 `null` "
        "(需要机型规格请用 `GET /{cluster_tag}/instance-groups`, 那条才回填 EC2 规格).\n\n"
        "**权限**: 仅平台超管 (`require_admin`).\n\n"
        "**数据源**: SageMaker `DescribeCluster` (取 ClusterArn) + `ListComputeQuotas` (实时)."
    ),
    responses={403: {"description": "非平台超管"}},
)
async def list_cluster_quotas_endpoint(
    cluster_tag: str,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """返回 ClusterQuotaList shape: {clusterArn, clusterTag, quotas[ComputeQuota]}."""
    name = _resolve_cluster_name(cluster_tag)
    detail = await cluster_describe.describe_cluster(name)
    cluster_arn = detail.get("ClusterArn")
    summaries = await compute_quota.list_compute_quotas(cluster_arn)
    return {
        "clusterArn": cluster_arn,
        "clusterTag": name,
        "quotas": [_quota_summary_to_camel(s) for s in summaries],
    }
