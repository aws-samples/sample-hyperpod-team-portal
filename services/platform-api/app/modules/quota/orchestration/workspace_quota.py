"""单 workspace 维度查询 + 集群维度列表 (DDB-only)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, status

from app.adapters.aws.ec2_instance_types import get_gpu_infos
from app.core.logging import get_logger
from app.modules.cluster import crud as cluster_crud
from app.modules.quota.api.schemas import ClusterQuotaList, ComputeQuota
from app.modules.quota.response.builders import (
    aws_quota_to_schema,
    build_cluster_quota_list,
)
from app.modules.workspace import crud as workspace_crud
from app.services.hyperpod_client import HyperPodClient

logger = get_logger(__name__)


async def _get_workspace_or_404(db: Any, ws_id: Any) -> dict[str, Any]:
    del db
    ws = await workspace_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    return ws


async def _tag_resource_pools(quota: ComputeQuota) -> None:
    """给 quota.resources 每项按 EC2 InstanceSpec 填 pool + 规格 (gpu_spec /
    gpu_type / accelerators / v_cpu / memory)。AWS DescribeComputeQuota 的
    v_cpu/memory 是 0.0 stub、Count 路径下 accelerators=0, 故这里用规格权威回填。
    查不到的机型保持缺省 (pool=cpu, 规格 0)。"""
    types = [r.instance_type for r in quota.resources if r.instance_type]
    if not types:
        return
    infos = await get_gpu_infos(types)
    for r in quota.resources:
        info = infos.get(r.instance_type)
        if info is None:
            continue
        if info.gpu_count > 0:
            r.pool = "gpu"
            r.gpu_spec = info.gpu_spec
            r.gpu_type = info.gpu_type
            r.accelerators = info.gpu_count
        else:
            r.pool = "cpu"
            r.gpu_spec = None
            r.gpu_type = None
            r.accelerators = 0
        if info.vcpu > 0:
            r.v_cpu = float(info.vcpu)
        if info.memory_gib > 0:
            r.memory_in_gi_b = info.memory_gib


async def get_workspace_quota(
    db: Any,
    hp: HyperPodClient,
    ws_id: Any,
) -> ComputeQuota:
    del db
    ws = await _get_workspace_or_404(None, ws_id)
    quota_id = ws.get("sagemaker_compute_quota_id") or ws.get("compute_quota_id")
    if not quota_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"workspace {ws.get('name')} has no ComputeQuota bound yet",
        )
    resp = await hp.describe_compute_quota(quota_id)
    quota = aws_quota_to_schema(resp)
    await _tag_resource_pools(quota)
    return quota


async def list_workspace_pool_instance_types(
    db: Any,
    hp: HyperPodClient,
    ws_id: Any,
    pool: Literal["gpu", "cpu"],
) -> list[str]:
    """取本 ws 配额中指定资源池 (gpu/cpu) 的机型名列表 (带 ml. 前缀, 去重保序)。

    复用入口 (开发机/训练/推理): 用户在 UI 选了 cpu/gpu 池, 后端用本方法拿到该池
    全部机型, 直接填进 CR 的 nodeAffinity `node.kubernetes.io/instance-type`
    (operator: In, values 是列表 → 调度器在这些机型的任一可用节点上起 Pod)。

    pool 判定权威来自 EC2 GpuInfo (见 _tag_resource_pools / get_gpu_infos):
    gpu_count>0 → gpu 池, 否则 cpu 池。注意降级语义: EC2 整批查询失败时所有机型
    归 cpu 池 (保守打底), 故 EC2 故障期间 cpu 池可能混入本应是 gpu 的机型。

    ws 未绑定 ComputeQuota → get_workspace_quota 抛 404 (调用方按需捕获)。
    该池无机型 → 返回 []。
    """
    quota = await get_workspace_quota(None, hp, ws_id)
    seen: set[str] = set()
    out: list[str] = []
    for r in quota.resources:
        if r.pool != pool or not r.instance_type or r.instance_type in seen:
            continue
        seen.add(r.instance_type)
        out.append(r.instance_type)
    return out


async def list_cluster_quotas(
    db: Any,
    hp: HyperPodClient,
    cluster_tag: str,
) -> ClusterQuotaList:
    del db
    cluster = await cluster_crud.get_cluster_by_tag(None, cluster_tag)
    if cluster is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"cluster not found: {cluster_tag}"
        )
    cluster_arn = cluster.get("hyperpod_cluster_arn")
    if not cluster_arn:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"cluster {cluster_tag} has no hyperpod_cluster_arn",
        )

    summaries = await hp.list_compute_quotas(cluster_arn=cluster_arn)
    quotas: list[ComputeQuota] = []
    for summary in summaries:
        qid = summary.get("ComputeQuotaId")
        if not qid:
            continue
        try:
            full = await hp.describe_compute_quota(qid)
            quotas.append(aws_quota_to_schema(full))
        except Exception as exc:
            logger.warning(
                "quota.list.describe_fallback", quota_id=qid, err=str(exc)
            )
            quotas.append(aws_quota_to_schema(summary))

    for q in quotas:
        await _tag_resource_pools(q)

    return build_cluster_quota_list(cluster_arn, cluster_tag, quotas)
