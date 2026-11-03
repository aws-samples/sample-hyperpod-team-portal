"""SageMaker scheduler config adapter 测试."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.aws import scheduler_config as sc


# ---------- to_wpc_name / to_bare_name helper ----------

def test_to_wpc_name_appends_suffix():
    assert sc.to_wpc_name("training") == "training-priority"
    assert sc.to_wpc_name("common") == "common-priority"


def test_to_wpc_name_idempotent_if_already_suffixed():
    # 已带后缀不重复加(防御性)
    assert sc.to_wpc_name("training-priority") == "training-priority"


def test_to_bare_name_strips_suffix():
    assert sc.to_bare_name("training-priority") == "training"
    assert sc.to_bare_name("common-priority") == "common"


def test_to_bare_name_no_suffix_returned_as_is():
    # 没带后缀的输入原样返回(不是所有 WPC 都必然带后缀,例如自建残留)
    assert sc.to_bare_name("aaa") == "aaa"


def test_to_bare_name_only_strips_trailing_suffix():
    # 名字中间含 "-priority" 子串不能误剥
    # 例: "my-priority-thing" 尾部不是 -priority,应原样
    assert sc.to_bare_name("my-priority-thing") == "my-priority-thing"


# ---------- resolve_cluster_arn ----------

@pytest.mark.asyncio
async def test_resolve_cluster_arn_calls_describe_cluster():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {
        "ClusterArn": "arn:aws:sagemaker:us-west-2:111:cluster/abc123",
        "ClusterName": "my-hp",
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        arn = await sc.resolve_cluster_arn("my-hp")
    assert arn == "arn:aws:sagemaker:us-west-2:111:cluster/abc123"
    fake_client.describe_cluster.assert_awaited_once_with(ClusterName="my-hp")


@pytest.mark.asyncio
async def test_resolve_cluster_arn_cached():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.resolve_cluster_arn("my-hp")
        await sc.resolve_cluster_arn("my-hp")
    # 只调一次 (第二次命中缓存)
    assert fake_client.describe_cluster.await_count == 1


@pytest.mark.asyncio
async def test_resolve_cluster_arn_empty_name_raises():
    with pytest.raises(sc.SchedulerConfigError, match="hyperpod_cluster_name"):
        await sc.resolve_cluster_arn("")


# ---------- resolve_config_id ----------

@pytest.mark.asyncio
async def test_resolve_config_id_returns_single_id():
    fake_client = AsyncMock()
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [
            {"ClusterSchedulerConfigId": "cfg1234567aa"}
        ]
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        cid = await sc.resolve_config_id("arn:x")
    assert cid == "cfg1234567aa"


@pytest.mark.asyncio
async def test_resolve_config_id_zero_configs_raises():
    fake_client = AsyncMock()
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": []
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        with pytest.raises(sc.SchedulerConfigError, match="cluster policy"):
            await sc.resolve_config_id("arn:x")


@pytest.mark.asyncio
async def test_resolve_config_id_multiple_configs_raises():
    fake_client = AsyncMock()
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [
            {"ClusterSchedulerConfigId": "cfg1"},
            {"ClusterSchedulerConfigId": "cfg2"},
        ]
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        with pytest.raises(sc.SchedulerConfigError, match="multiple"):
            await sc.resolve_config_id("arn:x")


@pytest.mark.asyncio
async def test_resolve_config_id_cached():
    fake_client = AsyncMock()
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.resolve_config_id("arn:x")
        await sc.resolve_config_id("arn:x")
    assert fake_client.list_cluster_scheduler_configs.await_count == 1


@pytest.mark.asyncio
async def test_resolve_cluster_arn_missing_arn_raises():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterName": "my-hp"}  # 无 ClusterArn
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        with pytest.raises(sc.SchedulerConfigError, match="ClusterArn"):
            await sc.resolve_cluster_arn("my-hp")


# ---------- 辅助: 把 AsyncMock 包成 async context manager (模拟 aioboto3 session.client()) ----------

class _ctx:
    def __init__(self, client): self._c = client
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


# ---------- list_priority_classes ----------

@pytest.mark.asyncio
async def test_list_priority_classes_maps_bare_to_wpc_name():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {
            "PriorityClasses": [
                {"Name": "inference", "Weight": 100},
                {"Name": "training", "Weight": 80},
                {"Name": "common", "Weight": 80},
            ]
        }
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        rows = await sc.list_priority_classes("my-hp")
    names = [r["name"] for r in rows]
    values = [r["value"] for r in rows]
    assert "inference-priority" in names
    assert "training-priority" in names
    assert "common-priority" in names
    assert values[0] == 100  # 最大在前
    assert all(r["description"] is None for r in rows)


@pytest.mark.asyncio
async def test_list_priority_classes_empty():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {"PriorityClasses": []}
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        rows = await sc.list_priority_classes("my-hp")
    assert rows == []


# ---------- upsert_priority_class ----------

@pytest.mark.asyncio
async def test_upsert_priority_class_creates_new():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {"PriorityClasses": [{"Name": "training", "Weight": 80}]},
        "ClusterSchedulerConfigVersion": 3,
    }
    fake_client.update_cluster_scheduler_config.return_value = {
        "ClusterSchedulerConfigVersion": 4
    }
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.upsert_priority_class("my-hp", bare_name="urgent", weight=95)
    call = fake_client.update_cluster_scheduler_config.await_args
    kwargs = call.kwargs
    assert kwargs["ClusterSchedulerConfigId"] == "cid1"
    assert kwargs["TargetVersion"] == 3
    names = {p["Name"] for p in kwargs["SchedulerConfig"]["PriorityClasses"]}
    assert names == {"training", "urgent"}


@pytest.mark.asyncio
async def test_upsert_priority_class_updates_existing_weight():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {"PriorityClasses": [{"Name": "training", "Weight": 80}]},
        "ClusterSchedulerConfigVersion": 5,
    }
    fake_client.update_cluster_scheduler_config.return_value = {}
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.upsert_priority_class("my-hp", bare_name="training", weight=88)
    call = fake_client.update_cluster_scheduler_config.await_args
    priorities = call.kwargs["SchedulerConfig"]["PriorityClasses"]
    assert priorities == [{"Name": "training", "Weight": 88}]


@pytest.mark.asyncio
async def test_upsert_priority_class_translates_update_failed():
    from botocore.exceptions import ClientError

    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {"PriorityClasses": []},
        "ClusterSchedulerConfigVersion": 1,
    }
    fake_client.update_cluster_scheduler_config.side_effect = ClientError(
        {"Error": {"Code": "InvalidRequestException", "Message": "already exists and is not managed by SageMaker"}},
        "UpdateClusterSchedulerConfig",
    )
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        with pytest.raises(sc.SchedulerConfigError, match="not managed by SageMaker"):
            await sc.upsert_priority_class("my-hp", bare_name="common", weight=80)


# ---------- delete_priority_class ----------

@pytest.mark.asyncio
async def test_delete_priority_class_removes_from_array():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {
            "PriorityClasses": [
                {"Name": "training", "Weight": 80},
                {"Name": "urgent", "Weight": 95},
            ]
        },
        "ClusterSchedulerConfigVersion": 7,
    }
    fake_client.update_cluster_scheduler_config.return_value = {}
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.delete_priority_class("my-hp", bare_name="urgent")
    call = fake_client.update_cluster_scheduler_config.await_args
    priorities = call.kwargs["SchedulerConfig"]["PriorityClasses"]
    assert priorities == [{"Name": "training", "Weight": 80}]
    assert call.kwargs["TargetVersion"] == 7


@pytest.mark.asyncio
async def test_delete_priority_class_absent_is_noop_but_still_updates():
    """删不存在的档: 数组不变, 但仍发一次 update (幂等)."""
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {"PriorityClasses": [{"Name": "training", "Weight": 80}]},
        "ClusterSchedulerConfigVersion": 1,
    }
    fake_client.update_cluster_scheduler_config.return_value = {}
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.delete_priority_class("my-hp", bare_name="not-there")
    call = fake_client.update_cluster_scheduler_config.await_args
    assert call.kwargs["SchedulerConfig"]["PriorityClasses"] == [
        {"Name": "training", "Weight": 80}
    ]


@pytest.mark.asyncio
async def test_delete_priority_class_last_entry_sends_empty_array():
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.return_value = {
        "SchedulerConfig": {"PriorityClasses": [{"Name": "solo", "Weight": 50}]},
        "ClusterSchedulerConfigVersion": 2,
    }
    fake_client.update_cluster_scheduler_config.return_value = {}
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        await sc.delete_priority_class("my-hp", bare_name="solo")
    call = fake_client.update_cluster_scheduler_config.await_args
    assert call.kwargs["SchedulerConfig"]["PriorityClasses"] == []


# ---------- describe-phase error translation ----------

@pytest.mark.asyncio
async def test_describe_phase_client_error_translated():
    from botocore.exceptions import ClientError
    fake_client = AsyncMock()
    fake_client.describe_cluster.return_value = {"ClusterArn": "arn:x"}
    fake_client.list_cluster_scheduler_configs.return_value = {
        "ClusterSchedulerConfigSummaries": [{"ClusterSchedulerConfigId": "cid1"}]
    }
    fake_client.describe_cluster_scheduler_config.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFound", "Message": "config gone"}},
        "DescribeClusterSchedulerConfig",
    )
    with patch.object(sc, "_sagemaker_client", return_value=_ctx(fake_client)):
        sc.reset_cache()
        with pytest.raises(sc.SchedulerConfigError, match="describe-cluster-scheduler-config failed"):
            await sc.list_priority_classes("my-hp")
