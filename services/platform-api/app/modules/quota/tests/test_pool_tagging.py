"""get_workspace_quota 按 EC2 GPU 数给 resource 填 pool + gpu_spec。"""
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
async def test_tag_gpu_and_cpu(monkeypatch):
    async def fake_infos(types):
        return {
            "ml.g6.12xlarge": InstanceSpec(gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0),
            "ml.m5.4xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0),
        }

    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)
    q = _quota("ml.g6.12xlarge", "ml.m5.4xlarge")
    await wq._tag_resource_pools(q)
    assert {r.instance_type: r.pool for r in q.resources} == {
        "ml.g6.12xlarge": "gpu",
        "ml.m5.4xlarge": "cpu",
    }
    assert q.resources[0].gpu_spec == "4×L4"
    assert q.resources[1].gpu_spec is None
    # CPU 机型也回填 vCPU/内存 (来自 InstanceSpec)
    assert q.resources[1].v_cpu == 16.0
    assert q.resources[1].memory_in_gi_b == 64.0
    assert q.resources[1].gpu_type is None
    assert q.resources[1].accelerators == 0


@pytest.mark.asyncio
async def test_tag_ec2_fail_all_cpu(monkeypatch):
    async def fake_infos(types):
        return {"ml.g6.12xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=16, memory_gib=64.0)}

    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)
    q = _quota("ml.g6.12xlarge")
    await wq._tag_resource_pools(q)
    assert q.resources[0].pool == "cpu"
    assert q.resources[0].gpu_spec is None


@pytest.mark.asyncio
async def test_tag_fills_vcpu_memory_accelerators(monkeypatch):
    async def fake_infos(types):
        return {
            "ml.g6.12xlarge": InstanceSpec(
                gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0
            ),
        }

    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)
    q = _quota("ml.g6.12xlarge")
    await wq._tag_resource_pools(q)
    r = q.resources[0]
    assert r.pool == "gpu"
    assert r.gpu_spec == "4×L4"
    assert r.gpu_type == "L4"
    assert r.accelerators == 4
    assert r.v_cpu == 48.0
    assert r.memory_in_gi_b == 192.0
