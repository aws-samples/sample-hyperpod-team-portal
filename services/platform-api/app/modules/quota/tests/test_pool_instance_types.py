"""list_workspace_pool_instance_types: 取本 ws 配额中某资源池的机型名列表。

开发机/训练/推理复用: 选 cpu 池 -> 拿该 ws 所有 CPU 机型填 CR nodeAffinity。
"""
import pytest

from app.adapters.aws.ec2_instance_types import InstanceSpec
from app.modules.quota.api.schemas import (
    ComputeQuota,
    ComputeQuotaResource,
    ComputeQuotaTarget,
)
from app.modules.quota.orchestration import workspace_quota as wq


def _quota(*types):
    return ComputeQuota(
        compute_quota_arn="arn:aws:sagemaker:us-west-2:1:compute-quota/q1",
        compute_quota_id="q1",
        name="team-a",
        cluster_arn="arn:aws:sagemaker:us-west-2:1:cluster/c1",
        target=ComputeQuotaTarget(team_name="team-a"),
        resources=[
            ComputeQuotaResource(instance_type=t, count=1) for t in types
        ],
    )


@pytest.mark.asyncio
async def test_cpu_pool_returns_cpu_types(monkeypatch):
    q = _quota("ml.g6.12xlarge", "ml.m5.4xlarge", "ml.c5.2xlarge")

    async def fake_get(db, hp, ws_id):
        await wq._tag_resource_pools(q)
        return q

    async def fake_infos(types):
        return {
            "ml.g6.12xlarge": InstanceSpec(gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0),
            "ml.m5.4xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
            "ml.c5.2xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
        }

    monkeypatch.setattr(wq, "get_workspace_quota", fake_get)
    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)

    out = await wq.list_workspace_pool_instance_types(None, None, "ws-1", "cpu")
    assert out == ["ml.m5.4xlarge", "ml.c5.2xlarge"]


@pytest.mark.asyncio
async def test_gpu_pool_returns_gpu_types(monkeypatch):
    q = _quota("ml.g6.12xlarge", "ml.m5.4xlarge")

    async def fake_get(db, hp, ws_id):
        await wq._tag_resource_pools(q)
        return q

    async def fake_infos(types):
        return {
            "ml.g6.12xlarge": InstanceSpec(gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0),
            "ml.m5.4xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
        }

    monkeypatch.setattr(wq, "get_workspace_quota", fake_get)
    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)

    out = await wq.list_workspace_pool_instance_types(None, None, "ws-1", "gpu")
    assert out == ["ml.g6.12xlarge"]


@pytest.mark.asyncio
async def test_dedup_preserves_order(monkeypatch):
    q = _quota("ml.m5.4xlarge", "ml.m5.4xlarge", "ml.c5.2xlarge")

    async def fake_get(db, hp, ws_id):
        await wq._tag_resource_pools(q)
        return q

    async def fake_infos(types):
        return {
            "ml.m5.4xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
            "ml.c5.2xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
        }

    monkeypatch.setattr(wq, "get_workspace_quota", fake_get)
    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)

    out = await wq.list_workspace_pool_instance_types(None, None, "ws-1", "cpu")
    assert out == ["ml.m5.4xlarge", "ml.c5.2xlarge"]


@pytest.mark.asyncio
async def test_empty_pool_returns_empty(monkeypatch):
    q = _quota("ml.g6.12xlarge")

    async def fake_get(db, hp, ws_id):
        await wq._tag_resource_pools(q)
        return q

    async def fake_infos(types):
        return {"ml.g6.12xlarge": InstanceSpec(gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0)}

    monkeypatch.setattr(wq, "get_workspace_quota", fake_get)
    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)

    out = await wq.list_workspace_pool_instance_types(None, None, "ws-1", "cpu")
    assert out == []
