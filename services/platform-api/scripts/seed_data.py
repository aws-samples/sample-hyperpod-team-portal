"""集群管理模块种子数据（本地开发用）

运行:
    cd services/platform-api
    python scripts/seed_data.py

特性:
- 幂等: 二次执行不会报错也不会产生重复行（UPSERT 语义 via ON CONFLICT）
- 3 team mock: team-a / team-b / team-c（workspace_id 用固定 UUID，后续 workspace 模块对接真表后替换）
- 数据覆盖: 1 cluster + 3 instance_groups + 5 nodes + 9 resource_quotas
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

# 允许脚本从 services/platform-api/ 根目录运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal, engine
from app.modules.cluster.models import (  # noqa: E402
    Cluster,
    InstanceGroup,
    NodeStatus,
    ResourceQuota,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed")


# ===== 固定 UUID（稳定引用，方便前端 mock 调试）=====
CLUSTER_ID = UUID("11111111-1111-4111-8111-111111111111")
IG_TEAM_A_ID = UUID("22222222-2222-4222-8222-22222222aaaa")
IG_TEAM_B_ID = UUID("22222222-2222-4222-8222-22222222bbbb")
IG_CPU_SHARED_ID = UUID("22222222-2222-4222-8222-22222222cccc")

# team workspace_id（workspace 模块未建表前先用固定 UUID 占位）
WS_TEAM_A = UUID("aaaaaaaa-0000-4000-8000-000000000001")
WS_TEAM_B = UUID("aaaaaaaa-0000-4000-8000-000000000002")
WS_TEAM_C = UUID("aaaaaaaa-0000-4000-8000-000000000003")

NOW = datetime.now(UTC)


# ===== Cluster 1 条 =====
def cluster_row() -> dict:
    return {
        "id": CLUSTER_ID,
        "cluster_tag": "hp-cluster-hypd-0507-9390",
        "type": "hyperpod",
        "region": "us-west-2",
        "state": "InService",
        "workspace_scope": "shared",
        "eks_cluster_name": "eks-hypd-0507-9390",
        "hyperpod_cluster_arn": "arn:aws:sagemaker:us-west-2:123456789012:cluster/abcd1234efgh",
        "last_synced_at": NOW,
        "metadata_json": {
            "note": "seeded from scripts/seed_data.py",
            "owner": "admin",
            "vpc_id": "vpc-mock-seed",
            "advanced_features": {
                "training_operator": {"enabled": True, "version": "0.2.0"},
                "inference_operator": {"enabled": True, "version": "v3.1"},
                "tiered_storage": {"enabled": False},
                "hami": {"enabled": False},
            },
        },
    }


# ===== InstanceGroup 3 条 =====
def instance_group_rows() -> list[dict]:
    return [
        {
            "id": IG_TEAM_A_ID,
            "cluster_id": CLUSTER_ID,
            "group_name": "accel-g5-team-a",
            "instance_type": "ml.g5.xlarge",
            "instance_count": 2,
            "target_count": 2,
            "availability_zone": "us-west-2a",
            "lifecycle_script": "s3://hypd-mock/lifecycle/team-a.sh",
            "threads_per_core": 2,
            "karpenter_managed": False,
            "ebs_volume_gb": 500,
            "deep_health_check_enabled": True,
            "deep_health_check_duration": "2h",
        },
        {
            "id": IG_TEAM_B_ID,
            "cluster_id": CLUSTER_ID,
            "group_name": "accel-g5-team-b",
            "instance_type": "ml.g5.xlarge",
            "instance_count": 2,
            "target_count": 2,
            "availability_zone": "us-west-2a",
            "lifecycle_script": "s3://hypd-mock/lifecycle/team-b.sh",
            "threads_per_core": 2,
            "karpenter_managed": False,
            "ebs_volume_gb": 500,
            "deep_health_check_enabled": True,
            "deep_health_check_duration": "2h",
        },
        {
            "id": IG_CPU_SHARED_ID,
            "cluster_id": CLUSTER_ID,
            "group_name": "cpu-shared",
            "instance_type": "ml.m5.xlarge",
            "instance_count": 1,
            "target_count": 1,
            "availability_zone": "us-west-2a",
            "lifecycle_script": "s3://hypd-mock/lifecycle/cpu-shared.sh",
            "threads_per_core": 2,
            "karpenter_managed": False,
            "ebs_volume_gb": 200,
            "deep_health_check_enabled": False,
            "deep_health_check_duration": "30m",
        },
    ]


# ===== NodeStatus 5 条（team-a 2 + team-b 2 + cpu-shared 1）=====
def node_status_rows() -> list[dict]:
    # ml.g5.xlarge: 1 GPU (A10G 24GB), 4 vCPU, 16 GiB; 使用 millicores/MiB 口径
    # ml.m5.xlarge: 0 GPU, 4 vCPU, 16 GiB
    g5_common = {
        "instance_type": "ml.g5.xlarge",
        "availability_zone": "us-west-2a",
        "lifecycle_state": "InService",
        "gpu_total": 1,
        "gpu_allocatable": 1,
        "cpu_total_millicores": 4000,
        "cpu_allocatable_millicores": 3800,
        "mem_total_mib": 16384,
        "mem_allocatable_mib": 15360,
        "hami_enabled": False,
        "last_heartbeat": NOW,
        "last_synced_at": NOW,
    }
    m5_common = {
        "instance_type": "ml.m5.xlarge",
        "availability_zone": "us-west-2a",
        "lifecycle_state": "InService",
        "gpu_total": 0,
        "gpu_allocatable": 0,
        "gpu_used": 0,
        "cpu_total_millicores": 4000,
        "cpu_allocatable_millicores": 3800,
        "mem_total_mib": 16384,
        "mem_allocatable_mib": 15360,
        "hami_enabled": False,
        "last_heartbeat": NOW,
        "last_synced_at": NOW,
    }

    return [
        # team-a 2 节点
        {
            "cluster_id": CLUSTER_ID,
            "instance_group_id": IG_TEAM_A_ID,
            "node_name": "ip-10-0-1-11.us-west-2.compute.internal",
            "instance_id": "i-0aaaaaa000000001",
            "health_status": "Schedulable",
            "gpu_used": 1,
            "cpu_used_millicores": 2200,
            "mem_used_mib": 8192,
            "pod_count": 3,
            "taints": [],
            "labels": {
                "sagemaker.amazonaws.com/node-health-status": "Schedulable",
                "platform.hypd.ai/workspace": "team-a",
                "beta.kubernetes.io/instance-type": "ml.g5.xlarge",
            },
            **g5_common,
        },
        {
            "cluster_id": CLUSTER_ID,
            "instance_group_id": IG_TEAM_A_ID,
            "node_name": "ip-10-0-1-12.us-west-2.compute.internal",
            "instance_id": "i-0aaaaaa000000002",
            "health_status": "Schedulable",
            "gpu_used": 0,
            "cpu_used_millicores": 800,
            "mem_used_mib": 3072,
            "pod_count": 1,
            "taints": [],
            "labels": {
                "sagemaker.amazonaws.com/node-health-status": "Schedulable",
                "platform.hypd.ai/workspace": "team-a",
                "beta.kubernetes.io/instance-type": "ml.g5.xlarge",
            },
            **g5_common,
        },
        # team-b 2 节点（一个不健康，用于演示故障路径）
        {
            "cluster_id": CLUSTER_ID,
            "instance_group_id": IG_TEAM_B_ID,
            "node_name": "ip-10-0-1-21.us-west-2.compute.internal",
            "instance_id": "i-0bbbbbb000000001",
            "health_status": "Schedulable",
            "gpu_used": 1,
            "cpu_used_millicores": 1800,
            "mem_used_mib": 6144,
            "pod_count": 2,
            "taints": [],
            "labels": {
                "sagemaker.amazonaws.com/node-health-status": "Schedulable",
                "platform.hypd.ai/workspace": "team-b",
                "beta.kubernetes.io/instance-type": "ml.g5.xlarge",
            },
            **g5_common,
        },
        {
            "cluster_id": CLUSTER_ID,
            "instance_group_id": IG_TEAM_B_ID,
            "node_name": "ip-10-0-1-22.us-west-2.compute.internal",
            "instance_id": "i-0bbbbbb000000002",
            "health_status": "Unhealthy",
            "lifecycle_state": "Replacing",
            "gpu_total": 1,
            "gpu_allocatable": 0,
            "gpu_used": 0,
            "cpu_total_millicores": 4000,
            "cpu_allocatable_millicores": 0,
            "cpu_used_millicores": 0,
            "mem_total_mib": 16384,
            "mem_allocatable_mib": 0,
            "mem_used_mib": 0,
            "pod_count": 0,
            "hami_enabled": False,
            "last_heartbeat": NOW,
            "last_synced_at": NOW,
            "instance_type": "ml.g5.xlarge",
            "availability_zone": "us-west-2a",
            "taints": [
                {"key": "node.kubernetes.io/unhealthy", "effect": "NoSchedule"}
            ],
            "labels": {
                "sagemaker.amazonaws.com/node-health-status": "Unhealthy",
                "platform.hypd.ai/workspace": "team-b",
                "beta.kubernetes.io/instance-type": "ml.g5.xlarge",
            },
        },
        # cpu-shared 1 节点
        {
            "cluster_id": CLUSTER_ID,
            "instance_group_id": IG_CPU_SHARED_ID,
            "node_name": "ip-10-0-2-11.us-west-2.compute.internal",
            "instance_id": "i-0cccccc000000001",
            "health_status": "Schedulable",
            "cpu_used_millicores": 1200,
            "mem_used_mib": 4096,
            "pod_count": 4,
            "taints": [],
            "labels": {
                "sagemaker.amazonaws.com/node-health-status": "Schedulable",
                "platform.hypd.ai/pool": "cpu-shared",
                "beta.kubernetes.io/instance-type": "ml.m5.xlarge",
            },
            **m5_common,
        },
    ]


# ===== ResourceQuota 9 条 =====
# 3 teams × 3 flavors; p5 / g5 以 GPU 为计数单位，cpu 以 millicores 计
def resource_quota_rows() -> list[dict]:
    base = [
        # flavor, gpu_type, gpu_quota, gpu_used, gpu_pending, cpu_q_milli, mem_q_mib
        ("p5-48xlarge", "H100", 16, 0, 0, 192_000, 2_097_152),
        ("g5-xlarge", "A10G", 4, 0, 0, 32_000, 65_536),
        ("cpu-only", None, None, 0, 0, 8_000, 32_768),
    ]
    # mock 实际使用量，贴近 node_status 的数据（team-a g5 used=1、team-b g5 used=1）
    usage_override = {
        (WS_TEAM_A, "g5-xlarge"): {"gpu_used": 1, "gpu_pending": 0, "cpu_used_millicores": 3000},
        (WS_TEAM_B, "g5-xlarge"): {"gpu_used": 1, "gpu_pending": 2, "cpu_used_millicores": 1800},
        (WS_TEAM_A, "cpu-only"): {"cpu_used_millicores": 1200},
    }

    rows: list[dict] = []
    for ws_id in (WS_TEAM_A, WS_TEAM_B, WS_TEAM_C):
        for flavor, gpu_type, gpu_q, gpu_u, gpu_p, cpu_q, mem_q in base:
            row = {
                "cluster_id": CLUSTER_ID,
                "workspace_id": ws_id,
                "flavor": flavor,
                "gpu_type": gpu_type,
                "gpu_quota": gpu_q,
                "gpu_used": gpu_u,
                "gpu_pending": gpu_p,
                "cpu_quota_millicores": cpu_q,
                "cpu_used_millicores": 0,
                "memory_quota_mib": mem_q,
                "memory_used_mib": 0,
                "priority_class": "normal",
                "preemption_policy": "Never",
            }
            if (ws_id, flavor) in usage_override:
                row.update(usage_override[(ws_id, flavor)])
            rows.append(row)
    return rows


# ===== 幂等 upsert 工具 =====
async def upsert_cluster(session) -> None:
    row = cluster_row()
    stmt = pg_insert(Cluster).values(**row)
    # 冲突键: cluster_tag UNIQUE
    stmt = stmt.on_conflict_do_update(
        index_elements=[Cluster.cluster_tag],
        set_={
            "state": row["state"],
            "eks_cluster_name": row["eks_cluster_name"],
            "hyperpod_cluster_arn": row["hyperpod_cluster_arn"],
            "last_synced_at": row["last_synced_at"],
            "metadata": row["metadata_json"],
        },
    )
    await session.execute(stmt)


async def upsert_instance_groups(session) -> None:
    for row in instance_group_rows():
        stmt = pg_insert(InstanceGroup).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=["cluster_id", "group_name"],
            set_={
                "instance_type": row["instance_type"],
                "instance_count": row["instance_count"],
                "target_count": row["target_count"],
                "availability_zone": row["availability_zone"],
                "lifecycle_script": row["lifecycle_script"],
                "ebs_volume_gb": row["ebs_volume_gb"],
                "deep_health_check_enabled": row["deep_health_check_enabled"],
                "deep_health_check_duration": row["deep_health_check_duration"],
            },
        )
        await session.execute(stmt)


async def upsert_nodes(session) -> None:
    for row in node_status_rows():
        stmt = pg_insert(NodeStatus).values(**row)
        # 冲突键: (cluster_id, node_name) UNIQUE
        update_cols = {
            k: row[k]
            for k in (
                "instance_group_id",
                "instance_id",
                "instance_type",
                "availability_zone",
                "health_status",
                "lifecycle_state",
                "gpu_total",
                "gpu_allocatable",
                "gpu_used",
                "cpu_total_millicores",
                "cpu_allocatable_millicores",
                "cpu_used_millicores",
                "mem_total_mib",
                "mem_allocatable_mib",
                "mem_used_mib",
                "pod_count",
                "last_heartbeat",
                "hami_enabled",
                "taints",
                "labels",
                "last_synced_at",
            )
            if k in row
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["cluster_id", "node_name"], set_=update_cols
        )
        await session.execute(stmt)


async def upsert_quotas(session) -> None:
    for row in resource_quota_rows():
        stmt = pg_insert(ResourceQuota).values(**row)
        # 冲突键: (cluster_id, workspace_id, flavor) UNIQUE
        update_cols = {
            k: row[k]
            for k in (
                "gpu_type",
                "gpu_quota",
                "gpu_used",
                "gpu_pending",
                "cpu_quota_millicores",
                "cpu_used_millicores",
                "memory_quota_mib",
                "memory_used_mib",
                "priority_class",
                "preemption_policy",
            )
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["cluster_id", "workspace_id", "flavor"], set_=update_cols
        )
        await session.execute(stmt)


# ===== 主流程 =====
async def verify_counts(session) -> dict[str, int]:
    counts = {}
    for label, model in (
        ("cluster", Cluster),
        ("instance_group", InstanceGroup),
        ("node_status", NodeStatus),
        ("resource_quota", ResourceQuota),
    ):
        result = await session.execute(select(model))
        counts[label] = len(result.scalars().all())
    return counts


async def main() -> None:
    logger.info("开始执行种子数据写入（幂等 upsert）...")
    async with AsyncSessionLocal() as session:
        # 校验表存在（A1 migration 未跑完前会报错）
        try:
            await session.execute(text("SELECT 1 FROM cluster LIMIT 1"))
        except Exception as e:
            logger.error("表 `cluster` 不存在。请先等 A1 执行 alembic upgrade head: %s", e)
            raise

        await upsert_cluster(session)
        logger.info("  ✅ Cluster 写入完成")
        await session.flush()

        await upsert_instance_groups(session)
        logger.info("  ✅ InstanceGroup 3 条写入完成")
        await session.flush()

        await upsert_nodes(session)
        logger.info("  ✅ NodeStatus 5 条写入完成")
        await session.flush()

        await upsert_quotas(session)
        logger.info("  ✅ ResourceQuota 9 条写入完成")

        await session.commit()

        counts = await verify_counts(session)
        logger.info("当前表记录数: %s", counts)

        expected = {"cluster": 1, "instance_group": 3, "node_status": 5, "resource_quota": 9}
        if counts != expected:
            logger.warning("⚠️ 条数与预期不一致（预期 %s），请排查", expected)
        else:
            logger.info("🎯 全部匹配预期 %s", expected)

    await engine.dispose()
    logger.info("完成。")


if __name__ == "__main__":
    asyncio.run(main())
