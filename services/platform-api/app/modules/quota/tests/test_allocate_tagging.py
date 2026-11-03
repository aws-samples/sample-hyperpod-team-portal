"""create/update quota 返回也回填规格 (写读路径契约一致)。

get_workspace_quota / list_cluster_quotas 早已 _tag_resource_pools, 但
create/update 的返回值没 tag → 同一对象 GET 有规格、POST/PATCH 却 pool=cpu、
v_cpu/memory=0。这两个测试证明写路径的 RETURN 值也被 tag。
"""

import pytest

from app.adapters.aws.ec2_instance_types import InstanceSpec
from app.modules.quota.api.schemas import (
    ComputeQuota,
    ComputeQuotaResource,
    ComputeQuotaTarget,
    CreateComputeQuotaPayload,
    UpdateComputeQuotaPayload,
)
from app.modules.quota.orchestration import allocate
from app.modules.quota.orchestration import workspace_quota as wq


def _untagged_quota():
    """一份未 tag 的 ComputeQuota (pool 缺省 cpu / v_cpu 0 / accelerators 0)。"""
    return ComputeQuota(
        compute_quota_arn="arn:aws:sagemaker:us-west-2:1:compute-quota/q1",
        compute_quota_id="q1",
        name="team-a",
        cluster_arn="arn:aws:sagemaker:us-west-2:1:cluster/c1",
        target=ComputeQuotaTarget(team_name="team-a"),
        resources=[ComputeQuotaResource(instance_type="ml.g6.12xlarge", count=1)],
    )


async def _fake_infos(types_):
    return {
        "ml.g6.12xlarge": InstanceSpec(
            gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0
        ),
    }


@pytest.mark.asyncio
async def test_create_returns_tagged(monkeypatch):
    async def fake_ws(db, ws_id):
        return {
            "name": "ws-a",
            "cluster_id": "cl-1",
            "workspace_id": "ws-1",
            "id": "ws-1",
        }

    monkeypatch.setattr(allocate.workspace_crud, "get_workspace", fake_ws)

    async def fake_cluster(db, cid):
        return {"hyperpod_cluster_arn": "arn:aws:sagemaker:us-west-2:1:cluster/c1"}

    monkeypatch.setattr(allocate.cluster_crud, "get_cluster_by_id", fake_cluster)

    async def fake_update_ws(*a, **k):
        return None

    monkeypatch.setattr(allocate.ws_repo, "update_workspace", fake_update_ws)

    # 用 stub 直接返回未 tag 的 quota, 绕开 AWS describe dict 形状
    monkeypatch.setattr(allocate, "aws_quota_to_schema", lambda _raw: _untagged_quota())
    # _tag_resource_pools 内部在 wq 命名空间查 get_gpu_infos
    monkeypatch.setattr(wq, "get_gpu_infos", _fake_infos)

    class FakeHp:
        async def create_compute_quota(self, payload):
            return {
                "ComputeQuotaId": "q1",
                "ComputeQuotaArn": "arn:aws:sagemaker:us-west-2:1:compute-quota/q1",
            }

        async def describe_compute_quota(self, qid):
            return {"ComputeQuotaId": qid}

    payload = CreateComputeQuotaPayload(
        name="team-a",
        resources=[ComputeQuotaResource(instance_type="ml.g6.12xlarge", count=1)],
        target=ComputeQuotaTarget(team_name="team-a"),
    )

    result = await allocate.create_workspace_quota(None, FakeHp(), "ws-1", payload)

    r = result.resources[0]
    assert r.pool == "gpu"
    assert r.accelerators == 4
    assert r.gpu_type == "L4"
    assert r.gpu_spec == "4×L4"
    assert r.v_cpu == 48.0
    assert r.memory_in_gi_b == 192.0


@pytest.mark.asyncio
async def test_update_returns_tagged(monkeypatch):
    async def fake_ws(db, ws_id):
        return {
            "name": "ws-a",
            "sagemaker_compute_quota_id": "q1",
            "workspace_id": "ws-1",
            "id": "ws-1",
        }

    monkeypatch.setattr(allocate.workspace_crud, "get_workspace", fake_ws)

    monkeypatch.setattr(allocate, "aws_quota_to_schema", lambda _raw: _untagged_quota())
    monkeypatch.setattr(wq, "get_gpu_infos", _fake_infos)

    class FakeHp:
        async def describe_compute_quota(self, qid):
            # current + refreshed 都取同一形状即可
            return {"ComputeQuotaId": qid, "ComputeQuotaVersion": 3}

        async def update_compute_quota(self, qid, version, payload):
            return None

    # payload 改了 count → 与当前不同 → 走真正 update 路径 (非 noop 短路)
    payload = UpdateComputeQuotaPayload(
        resources=[ComputeQuotaResource(instance_type="ml.g6.12xlarge", count=8)],
    )

    result = await allocate.update_workspace_quota(None, FakeHp(), "ws-1", payload)

    r = result.resources[0]
    assert r.pool == "gpu"
    assert r.accelerators == 4
    assert r.gpu_type == "L4"
    assert r.gpu_spec == "4×L4"
    assert r.v_cpu == 48.0
    assert r.memory_in_gi_b == 192.0


@pytest.mark.asyncio
async def test_update_noop_returns_tagged(monkeypatch):
    """无变化短路 (payload==current → unchanged) 也回填规格。

    也验证真的走了 noop 分支 (update_compute_quota 没被调)。
    """
    async def fake_ws(db, ws_id):
        return {
            "name": "ws-a",
            "sagemaker_compute_quota_id": "q1",
            "workspace_id": "ws-1",
            "id": "ws-1",
        }

    monkeypatch.setattr(allocate.workspace_crud, "get_workspace", fake_ws)

    # current = 未 tag 的 quota (1× ml.g6.12xlarge count=1)
    monkeypatch.setattr(allocate, "aws_quota_to_schema", lambda _raw: _untagged_quota())
    monkeypatch.setattr(wq, "get_gpu_infos", _fake_infos)

    class FakeHp:
        def __init__(self):
            self.update_called = False

        async def describe_compute_quota(self, qid):
            return {"ComputeQuotaId": qid, "ComputeQuotaVersion": 3}

        async def update_compute_quota(self, qid, version, payload):
            self.update_called = True
            return None

    # payload.resources 与 current 完全相同, 其余 None → merged==cur → unchanged
    payload = UpdateComputeQuotaPayload(
        resources=[ComputeQuotaResource(instance_type="ml.g6.12xlarge", count=1)],
    )

    hp = FakeHp()
    result = await allocate.update_workspace_quota(None, hp, "ws-1", payload)

    assert hp.update_called is False  # 确实命中 noop 短路分支
    r = result.resources[0]
    assert r.pool == "gpu"
    assert r.accelerators == 4
    assert r.gpu_type == "L4"
    assert r.gpu_spec == "4×L4"
    assert r.v_cpu == 48.0
    assert r.memory_in_gi_b == 192.0
