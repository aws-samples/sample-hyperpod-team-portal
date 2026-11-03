"""response/builders.py 单测 · ORM → dict 纯函数

用 SimpleNamespace 模拟 ORM 对象，避免起 DB。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.cluster.response.builders import (
    build_cluster_info,
    build_quota_flat,
    build_quota_flavor_node,
    build_quotas_flat_list,
    build_quotas_tree,
)

# =====================================================================
# fixtures
# =====================================================================


def _make_quota(
    *,
    workspace_id: UUID | None = None,
    flavor: str = "p5-48xlarge",
    gpu_type: str | None = "H100",
    gpu_quota: int = 8,
    gpu_used: int = 2,
    gpu_pending: int = 1,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    """模拟 ResourceQuota ORM 对象"""
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        flavor=flavor,
        gpu_type=gpu_type,
        gpu_quota=gpu_quota,
        gpu_used=gpu_used,
        gpu_pending=gpu_pending,
        cpu_quota_millicores=16000,
        cpu_used_millicores=4000,
        memory_quota_mib=65536,
        memory_used_mib=16384,
        priority_class="normal",
        preemption_policy="Never",
        updated_at=updated_at or datetime(2026, 5, 12, 10, 0, tzinfo=UTC),
    )


def _make_cluster(
    *,
    cluster_tag: str = "hyperpod-prod-01",
    cluster_type: str = "hyperpod",
    last_synced: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        cluster_tag=cluster_tag,
        type=cluster_type,
        region="us-west-2",
        state="InService",
        workspace_scope="shared",
        eks_cluster_name="hypd-prod",
        hyperpod_cluster_arn="arn:aws:sagemaker:us-west-2:123:cluster/foo",
        last_synced_at=last_synced,
        created_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
    )


# =====================================================================
# build_quota_flat
# =====================================================================


class TestBuildQuotaFlat:
    def test_basic_shape_and_usage_pct(self) -> None:
        q = _make_quota(gpu_quota=10, gpu_used=3)
        out = build_quota_flat(q)

        assert out["flavor"] == "p5-48xlarge"
        assert out["gpu_type"] == "H100"
        assert out["gpu"] == {
            "quota": 10,
            "used": 3,
            "pending": 1,
            "usage_pct": 30.0,
        }
        assert out["cpu_millicores"]["quota"] == 16000
        assert out["memory_mib"]["used"] == 16384
        assert out["priority_class"] == "normal"
        assert out["preemption_policy"] == "Never"
        assert out["updated_at"] == "2026-05-12T10:00:00+00:00"

    def test_null_workspace_serialized_as_none(self) -> None:
        q = _make_quota(workspace_id=None)
        out = build_quota_flat(q)
        assert out["workspace_id"] is None

    def test_workspace_id_stringified(self) -> None:
        ws_id = uuid4()
        q = _make_quota(workspace_id=ws_id)
        out = build_quota_flat(q)
        assert out["workspace_id"] == str(ws_id)

    def test_null_gpu_quota_usage_pct_is_zero(self) -> None:
        q = _make_quota(gpu_quota=0, gpu_used=5)
        out = build_quota_flat(q)
        assert out["gpu"]["usage_pct"] == 0.0

    def test_none_updated_at(self) -> None:
        q = _make_quota()
        q.updated_at = None
        out = build_quota_flat(q)
        assert out["updated_at"] is None


# =====================================================================
# build_quotas_flat_list
# =====================================================================


class TestBuildQuotasFlatList:
    def test_empty_list(self) -> None:
        assert build_quotas_flat_list([]) == []

    def test_multiple_quotas(self) -> None:
        q1 = _make_quota(flavor="p5-48xlarge", gpu_quota=16, gpu_used=8)
        q2 = _make_quota(flavor="g5-xlarge", gpu_quota=4, gpu_used=1, gpu_type="A10G")
        out = build_quotas_flat_list([q1, q2])
        assert len(out) == 2
        assert out[0]["flavor"] == "p5-48xlarge"
        assert out[0]["gpu"]["usage_pct"] == 50.0
        assert out[1]["gpu_type"] == "A10G"
        assert out[1]["gpu"]["usage_pct"] == 25.0


# =====================================================================
# build_quota_flavor_node
# =====================================================================


class TestBuildQuotaFlavorNode:
    def test_id_composition_with_ws_key(self) -> None:
        q = _make_quota(flavor="p5-48xlarge")
        node = build_quota_flavor_node(q, ws_key="shared")
        assert node["id"] == "ws-shared-p5-48xlarge"
        assert node["level"] == "flavor"

    def test_id_composition_with_uuid_ws(self) -> None:
        q = _make_quota(flavor="g5-xlarge")
        node = build_quota_flavor_node(q, ws_key="abc123")
        assert node["id"] == "ws-abc123-g5-xlarge"


# =====================================================================
# build_quotas_tree
# =====================================================================


class TestBuildQuotasTree:
    def test_empty_tree(self) -> None:
        cluster_id = uuid4()
        tree = build_quotas_tree(cluster_id, [])
        assert tree["view"] == "tree"
        assert tree["cluster_id"] == str(cluster_id)
        assert tree["tree"][0]["level"] == "cluster"
        assert tree["tree"][0]["children"] == []

    def test_shared_bucket_for_null_workspace(self) -> None:
        q1 = _make_quota(workspace_id=None, flavor="p5-48xlarge")
        q2 = _make_quota(workspace_id=None, flavor="g5-xlarge")
        tree = build_quotas_tree(uuid4(), [q1, q2])

        root = tree["tree"][0]
        assert len(root["children"]) == 1  # 都归到 shared
        ws_node = root["children"][0]
        assert ws_node["name"] == "shared"
        assert ws_node["level"] == "workspace"
        assert len(ws_node["children"]) == 2

    def test_separate_bucket_per_workspace(self) -> None:
        ws_a = uuid4()
        ws_b = uuid4()
        q_a = _make_quota(workspace_id=ws_a)
        q_b = _make_quota(workspace_id=ws_b)
        tree = build_quotas_tree(uuid4(), [q_a, q_b])
        ws_keys = {child["name"] for child in tree["tree"][0]["children"]}
        assert ws_keys == {str(ws_a), str(ws_b)}


# =====================================================================
# build_cluster_info
# =====================================================================


class TestBuildClusterInfo:
    def test_fields_present(self) -> None:
        c = _make_cluster(
            last_synced=datetime(2026, 5, 12, 9, 0, tzinfo=UTC)
        )
        out = build_cluster_info(c)

        assert out["cluster_tag"] == "hyperpod-prod-01"
        assert out["type"] == "hyperpod"
        assert out["region"] == "us-west-2"
        assert out["last_synced_at"] == "2026-05-12T09:00:00+00:00"
        assert out["created_at"] == "2026-05-01T00:00:00+00:00"
        assert out["id"] == str(c.id)

    def test_none_last_synced(self) -> None:
        c = _make_cluster(last_synced=None)
        out = build_cluster_info(c)
        assert out["last_synced_at"] is None
