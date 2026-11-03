"""update_workspace_quota 无变化短路 (AWS 对相同数据抛 ValidationException, 须幂等)。"""
from unittest.mock import AsyncMock

import pytest

from app.modules.quota.api.schemas import UpdateComputeQuotaPayload
from app.modules.quota.orchestration import allocate


# 一份 AWS describe_compute_quota 形状的当前配额 (Count 配额模式)
_CURRENT_AWS = {
    "ComputeQuotaArn": "arn:aws:sagemaker:us-west-2:1:compute-quota/q1",
    "ComputeQuotaId": "q1",
    "Name": "team-a",
    "ClusterArn": "arn:aws:sagemaker:us-west-2:1:cluster/c1",
    "ActivationState": "Enabled",
    "Status": "Created",
    "ComputeQuotaVersion": 3,
    "ComputeQuotaConfig": {
        "ComputeQuotaResources": [{"InstanceType": "ml.g6.12xlarge", "Count": 2}],
        "PreemptTeamTasks": "LowerPriority",
    },
    "ComputeQuotaTarget": {"TeamName": "team-a", "FairShareWeight": 50},
}


def _fake_hp() -> AsyncMock:
    hp = AsyncMock()
    hp.describe_compute_quota = AsyncMock(return_value=dict(_CURRENT_AWS))
    hp.update_compute_quota = AsyncMock()
    return hp


@pytest.mark.asyncio
async def test_update_noop_skips_aws(monkeypatch):
    """空 payload (各字段 None → merged 全取当前值) → 无变化 → 不调 AWS update。"""
    monkeypatch.setattr(
        allocate.workspace_crud, "get_workspace",
        AsyncMock(return_value={"sagemaker_compute_quota_id": "q1", "name": "ws"}),
    )
    hp = _fake_hp()
    payload = UpdateComputeQuotaPayload()  # 全 None

    out = await allocate.update_workspace_quota(None, hp, "ws-1", payload)

    hp.update_compute_quota.assert_not_awaited()  # 短路: 没调 AWS
    assert out.compute_quota_id == "q1"


@pytest.mark.asyncio
async def test_update_changed_calls_aws(monkeypatch):
    """payload 改了 resources → 有变化 → 正常调 AWS update。"""
    monkeypatch.setattr(
        allocate.workspace_crud, "get_workspace",
        AsyncMock(return_value={"sagemaker_compute_quota_id": "q1", "name": "ws"}),
    )
    hp = _fake_hp()
    from app.modules.quota.api.schemas import ComputeQuotaResource
    payload = UpdateComputeQuotaPayload(
        resources=[ComputeQuotaResource(instance_type="ml.g6.12xlarge", count=8)],
    )

    await allocate.update_workspace_quota(None, hp, "ws-1", payload)

    hp.update_compute_quota.assert_awaited_once()  # 有变化: 调了 AWS
