"""response/builders.py · AWS dict ↔ Pydantic 翻译单测."""

from __future__ import annotations

from app.modules.quota.api.schemas import (
    AbsoluteBorrowLimit,
    ComputeQuota,
    ComputeQuotaResource,
    ComputeQuotaTarget,
    ResourceSharingConfig,
)
from app.modules.quota.response.builders import (
    aws_quota_to_schema,
    aws_resource_to_schema,
    aws_sharing_to_schema,
    aws_target_to_schema,
    build_cluster_quota_list,
    build_quota_config_payload,
    compute_cluster_totals,
    schema_resource_to_aws,
    schema_sharing_to_aws,
)

# ============================================================
# AWS → schema
# ============================================================

class TestAwsResourceToSchema:
    def test_full_fields(self) -> None:
        d = {
            "InstanceType": "ml.p4d.24xlarge",
            "Count": 2,
            "Accelerators": 8,
            "VCpu": 96.0,
            "MemoryInGiB": 1152.0,
        }
        r = aws_resource_to_schema(d)
        assert r.instance_type == "ml.p4d.24xlarge"
        assert r.count == 2
        assert r.accelerators == 8
        assert r.v_cpu == 96.0
        assert r.memory_in_gi_b == 1152.0

    def test_missing_fields_default_zero(self) -> None:
        r = aws_resource_to_schema({"InstanceType": "ml.t3.large"})
        assert r.count == 0
        assert r.accelerators == 0
        assert r.v_cpu == 0.0


class TestAwsSharingToSchema:
    def test_none_returns_default(self) -> None:
        s = aws_sharing_to_schema(None)
        assert s.strategy == "LendAndBorrow"
        assert s.borrow_limit is None
        assert s.absolute_borrow_limits == []

    def test_with_borrow_limit(self) -> None:
        s = aws_sharing_to_schema({"Strategy": "Lend", "BorrowLimit": 5000})
        assert s.strategy == "Lend"
        assert s.borrow_limit == 5000

    def test_with_absolute_limits(self) -> None:
        s = aws_sharing_to_schema(
            {
                "Strategy": "LendAndBorrow",
                "AbsoluteBorrowLimits": [
                    {"InstanceType": "ml.g5.8xlarge", "Accelerators": 16}
                ],
            }
        )
        assert len(s.absolute_borrow_limits) == 1
        assert s.absolute_borrow_limits[0].instance_type == "ml.g5.8xlarge"
        assert s.absolute_borrow_limits[0].accelerators == 16


class TestAwsTargetToSchema:
    def test_fairshare_default_1(self) -> None:
        t = aws_target_to_schema({"TeamName": "team-a"})
        assert t.team_name == "team-a"
        assert t.fair_share_weight == 1  # AWS 不回传时 default

    def test_explicit_weight(self) -> None:
        t = aws_target_to_schema({"TeamName": "team-b", "FairShareWeight": 50})
        assert t.fair_share_weight == 50


class TestAwsQuotaToSchema:
    def test_describe_shape(self) -> None:
        d = {
            "ComputeQuotaArn": "arn:aws:sagemaker:us-west-2:123:compute-quota/abc",
            "ComputeQuotaId": "abc",
            "Name": "team-a-quota",
            "Description": "team a",
            "ClusterArn": "arn:aws:sagemaker:us-west-2:123:cluster/xyz",
            "ActivationState": "Enabled",
            "Status": "Created",
            "ComputeQuotaVersion": 3,
            "ComputeQuotaConfig": {
                "ComputeQuotaResources": [
                    {
                        "InstanceType": "ml.p4d.24xlarge",
                        "Count": 2,
                        "Accelerators": 8,
                        "VCpu": 96.0,
                        "MemoryInGiB": 1152.0,
                    }
                ],
                "ResourceSharingConfig": {"Strategy": "LendAndBorrow"},
                "PreemptTeamTasks": "LowerPriority",
            },
            "ComputeQuotaTarget": {"TeamName": "team-a", "FairShareWeight": 10},
        }
        q = aws_quota_to_schema(d)
        assert isinstance(q, ComputeQuota)
        assert q.compute_quota_id == "abc"
        assert q.compute_quota_version == 3
        assert len(q.resources) == 1
        assert q.resources[0].accelerators == 8
        assert q.target.team_name == "team-a"
        assert q.target.fair_share_weight == 10


# ============================================================
# schema → AWS
# ============================================================

class TestSchemaResourceToAws:
    def test_skips_zero_optional(self) -> None:
        r = ComputeQuotaResource(instance_type="ml.t3.large", count=1)
        out = schema_resource_to_aws(r)
        assert out == {"InstanceType": "ml.t3.large", "Count": 1}
        # 零值的 accelerators/v_cpu/memory 不应被带上 (AWS 可能拒绝 0)
        assert "Accelerators" not in out
        assert "VCpu" not in out
        assert "MemoryInGiB" not in out

    def test_count_excludes_fine_grained(self) -> None:
        # SageMaker 约束: Count 与 accelerators/vcpu/memory 互斥.
        # count>0 时只发 Count, 即使 schema 同时带了细粒度 (describe 回来会自动补)
        r = ComputeQuotaResource(
            instance_type="ml.p4d.24xlarge",
            count=2,
            accelerators=8,
            v_cpu=96.0,
            memory_in_gi_b=1152.0,
        )
        out = schema_resource_to_aws(r)
        assert out == {"InstanceType": "ml.p4d.24xlarge", "Count": 2}
        assert "Accelerators" not in out
        assert "VCpu" not in out
        assert "MemoryInGiB" not in out

    def test_fine_grained_when_no_count(self) -> None:
        # count<=0 → 走细粒度资源配额
        r = ComputeQuotaResource(
            instance_type="ml.p4d.24xlarge",
            count=0,
            accelerators=8,
            v_cpu=96.0,
            memory_in_gi_b=1152.0,
        )
        out = schema_resource_to_aws(r)
        assert "Count" not in out
        assert out["Accelerators"] == 8
        assert out["VCpu"] == 96.0
        assert out["MemoryInGiB"] == 1152.0


class TestSchemaSharingToAws:
    def test_borrow_limit_mode(self) -> None:
        s = ResourceSharingConfig(strategy="Lend", borrow_limit=5000)
        out = schema_sharing_to_aws(s)
        assert out["Strategy"] == "Lend"
        assert out["BorrowLimit"] == 5000
        assert "AbsoluteBorrowLimits" not in out

    def test_absolute_mode_wins_over_borrow_limit(self) -> None:
        # 二者互斥, 文档说以 absolute 为准
        s = ResourceSharingConfig(
            borrow_limit=999,
            absolute_borrow_limits=[
                AbsoluteBorrowLimit(instance_type="ml.g5.8xlarge", count=4)
            ],
        )
        out = schema_sharing_to_aws(s)
        assert "BorrowLimit" not in out
        assert len(out["AbsoluteBorrowLimits"]) == 1
        # 未设置的 None 字段不应泄到 AWS payload
        entry = out["AbsoluteBorrowLimits"][0]
        assert entry == {"InstanceType": "ml.g5.8xlarge", "Count": 4}


class TestBuildQuotaConfigPayload:
    def test_shape(self) -> None:
        payload = build_quota_config_payload(
            resources=[
                ComputeQuotaResource(instance_type="ml.g5.xlarge", count=1, accelerators=1)
            ],
            sharing=ResourceSharingConfig(strategy="Lend"),
            preempt="LowerPriority",
        )
        assert "ComputeQuotaResources" in payload
        assert payload["ResourceSharingConfig"]["Strategy"] == "Lend"
        assert payload["PreemptTeamTasks"] == "LowerPriority"


# ============================================================
# Cluster 聚合
# ============================================================

def _mk_quota(resources: list[ComputeQuotaResource]) -> ComputeQuota:
    return ComputeQuota(
        compute_quota_arn="arn:aws:x",
        compute_quota_id="q1",
        name="q",
        cluster_arn="arn:aws:c",
        resources=resources,
        target=ComputeQuotaTarget(team_name="team-a"),
    )


class TestComputeClusterTotals:
    def test_empty_list(self) -> None:
        t = compute_cluster_totals([])
        assert t.total_accelerators == 0

    def test_multi_quota(self) -> None:
        q1 = _mk_quota(
            [ComputeQuotaResource(instance_type="ml.p4d", count=2, accelerators=8,
                                   v_cpu=96.0, memory_in_gi_b=1152.0)]
        )
        q2 = _mk_quota(
            [ComputeQuotaResource(instance_type="ml.g5", count=3, accelerators=4,
                                   v_cpu=48.0, memory_in_gi_b=192.0)]
        )
        t = compute_cluster_totals([q1, q2])
        assert t.total_accelerators == 2 * 8 + 3 * 4
        assert t.total_v_cpu == round(2 * 96.0 + 3 * 48.0, 2)
        assert t.total_memory_in_gi_b == round(2 * 1152.0 + 3 * 192.0, 2)


class TestBuildClusterQuotaList:
    def test_returns_pydantic_with_totals(self) -> None:
        q = _mk_quota(
            [ComputeQuotaResource(instance_type="ml.g5", count=1, accelerators=1)]
        )
        lst = build_cluster_quota_list("arn:aws:c", "cluster-a", [q])
        assert lst.cluster_arn == "arn:aws:c"
        assert lst.cluster_tag == "cluster-a"
        assert len(lst.quotas) == 1
        assert lst.totals.total_accelerators == 1
