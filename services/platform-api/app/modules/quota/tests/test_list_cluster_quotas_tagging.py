"""list_cluster_quotas 也回填规格 (集群总配额不再显示 0)."""

import pytest

from app.adapters.aws.ec2_instance_types import InstanceSpec
from app.modules.quota.api.schemas import (
    ComputeQuota,
    ComputeQuotaResource,
    ComputeQuotaTarget,
)
from app.modules.quota.orchestration import workspace_quota as wq


@pytest.mark.asyncio
async def test_list_cluster_quotas_tags_resources(monkeypatch):
    async def fake_get_cluster(db, tag):
        return {"hyperpod_cluster_arn": "arn:aws:sagemaker:us-west-2:1:cluster/c1"}

    monkeypatch.setattr(wq.cluster_crud, "get_cluster_by_tag", fake_get_cluster)

    def fake_schema(_raw):
        return ComputeQuota(
            compute_quota_arn="arn:aws:sagemaker:us-west-2:1:compute-quota/q1",
            compute_quota_id="q1",
            name="team-a",
            cluster_arn="arn:aws:sagemaker:us-west-2:1:cluster/c1",
            target=ComputeQuotaTarget(team_name="team-a"),
            resources=[ComputeQuotaResource(instance_type="ml.g6.12xlarge", count=1)],
        )

    monkeypatch.setattr(wq, "aws_quota_to_schema", fake_schema)

    async def fake_infos(types_):
        return {
            "ml.g6.12xlarge": InstanceSpec(
                gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0
            ),
        }

    monkeypatch.setattr(wq, "get_gpu_infos", fake_infos)

    class FakeHp:
        async def list_compute_quotas(self, cluster_arn):
            return [{"ComputeQuotaId": "q1"}]

        async def describe_compute_quota(self, qid):
            return {"ComputeQuotaId": qid}

    result = await wq.list_cluster_quotas(None, FakeHp(), "cluster-x")
    r = result.quotas[0].resources[0]
    assert r.pool == "gpu"
    assert r.accelerators == 4
    assert r.v_cpu == 48.0
    assert r.memory_in_gi_b == 192.0
