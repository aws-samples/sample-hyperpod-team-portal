"""配额模块种子数据 (M1)

- 6 条 resource_quota: 3 workspace × 2 flavor (linnjia-demo-ig GPU + cpu-shared)
- GPU 总配额 10 (超发演示切片) · CPU 60000m · Memory 130000 MiB (team-a 主力 / b 测试 / c 新手)
- 幂等: (cluster_id, workspace_id, flavor) UNIQUE 兜底 ON CONFLICT DO UPDATE

前置条件:
  1. scripts/seed_data.py 已跑 (cluster + instance_group 存在)
  2. scripts/seed_workspace.py 已跑 (3 user + 3 workspace 存在)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import AsyncSessionLocal, engine
from app.modules.cluster.models import Cluster, ResourceQuota
from app.modules.workspace.models import Workspace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_quota")


CLUSTER_TAG = "hp-cluster-hypd-0507-9390"

# 6 条配额 (3 ws × 2 flavor)
QUOTAS: list[dict] = [
    # team-a-nlp 主力 (GPU 用得最狠)
    {
        "ws_name": "team-a-nlp",
        "flavor": "linnjia-demo-ig",
        "gpu_type": "A10G",
        "gpu_quota": 6,
        "gpu_used": 4,
        "gpu_pending": 1,
        "cpu_quota_millicores": 30000,
        "cpu_used_millicores": 18000,
        "memory_quota_mib": 65536,
        "memory_used_mib": 42000,
        "priority_class": "high",
        "preemption_policy": "Never",
    },
    {
        "ws_name": "team-a-nlp",
        "flavor": "cpu-shared",
        "gpu_type": None,
        "gpu_quota": None,
        "gpu_used": 0,
        "gpu_pending": 0,
        "cpu_quota_millicores": 8000,
        "cpu_used_millicores": 3200,
        "memory_quota_mib": 16384,
        "memory_used_mib": 5000,
        "priority_class": "normal",
        "preemption_policy": "Never",
    },
    # team-b-vision (中等负载)
    {
        "ws_name": "team-b-vision",
        "flavor": "linnjia-demo-ig",
        "gpu_type": "A10G",
        "gpu_quota": 3,
        "gpu_used": 1,
        "gpu_pending": 0,
        "cpu_quota_millicores": 15000,
        "cpu_used_millicores": 5000,
        "memory_quota_mib": 32768,
        "memory_used_mib": 10000,
        "priority_class": "normal",
        "preemption_policy": "LowerPriority",
    },
    {
        "ws_name": "team-b-vision",
        "flavor": "cpu-shared",
        "gpu_type": None,
        "gpu_quota": None,
        "gpu_used": 0,
        "gpu_pending": 0,
        "cpu_quota_millicores": 4000,
        "cpu_used_millicores": 1000,
        "memory_quota_mib": 8192,
        "memory_used_mib": 2000,
        "priority_class": "normal",
        "preemption_policy": "Never",
    },
    # team-c-recsys (新上线, 空闲)
    {
        "ws_name": "team-c-recsys",
        "flavor": "linnjia-demo-ig",
        "gpu_type": "A10G",
        "gpu_quota": 1,
        "gpu_used": 0,
        "gpu_pending": 0,
        "cpu_quota_millicores": 5000,
        "cpu_used_millicores": 0,
        "memory_quota_mib": 10240,
        "memory_used_mib": 0,
        "priority_class": "low",
        "preemption_policy": "LowerPriority",
    },
    {
        "ws_name": "team-c-recsys",
        "flavor": "cpu-shared",
        "gpu_type": None,
        "gpu_quota": None,
        "gpu_used": 0,
        "gpu_pending": 0,
        "cpu_quota_millicores": 2000,
        "cpu_used_millicores": 0,
        "memory_quota_mib": 4096,
        "memory_used_mib": 0,
        "priority_class": "normal",
        "preemption_policy": "Never",
    },
]


async def get_cluster_id(session) -> str:
    res = await session.execute(select(Cluster).where(Cluster.cluster_tag == CLUSTER_TAG))
    cluster = res.scalar_one_or_none()
    if cluster is None:
        raise RuntimeError(f"cluster '{CLUSTER_TAG}' 不存在 — 先跑 seed_data.py")
    return cluster.id


async def get_ws_by_name(session, cluster_id) -> dict[str, str]:
    res = await session.execute(
        select(Workspace).where(Workspace.cluster_id == cluster_id)
    )
    return {w.name: w.id for w in res.scalars().all()}


async def upsert_quotas(session, cluster_id, ws_id_by_name) -> int:
    """ON CONFLICT (cluster_id, workspace_id, flavor) DO UPDATE"""
    missing = [q["ws_name"] for q in QUOTAS if q["ws_name"] not in ws_id_by_name]
    if missing:
        raise RuntimeError(f"workspace 未 seed: {missing} — 先跑 seed_workspace.py")

    for q in QUOTAS:
        payload = {
            "cluster_id": cluster_id,
            "workspace_id": ws_id_by_name[q["ws_name"]],
            "flavor": q["flavor"],
            "gpu_type": q["gpu_type"],
            "gpu_quota": q["gpu_quota"],
            "gpu_used": q["gpu_used"],
            "gpu_pending": q["gpu_pending"],
            "cpu_quota_millicores": q["cpu_quota_millicores"],
            "cpu_used_millicores": q["cpu_used_millicores"],
            "memory_quota_mib": q["memory_quota_mib"],
            "memory_used_mib": q["memory_used_mib"],
            "priority_class": q["priority_class"],
            "preemption_policy": q["preemption_policy"],
        }
        stmt = pg_insert(ResourceQuota).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["cluster_id", "workspace_id", "flavor"],
            set_={
                k: payload[k]
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
            },
        )
        await session.execute(stmt)
    await session.flush()
    return len(QUOTAS)


async def verify_counts(session, cluster_id) -> int:
    res = await session.execute(
        select(ResourceQuota).where(ResourceQuota.cluster_id == cluster_id)
    )
    return len(list(res.scalars().all()))


async def main() -> None:
    logger.info("开始执行 quota 种子数据写入 (幂等 upsert)...")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text("SELECT 1 FROM resource_quota LIMIT 1"))
        except Exception as e:
            logger.error("表 resource_quota 未创建 — 请先 `alembic upgrade head`: %s", e)
            raise

        cluster_id = await get_cluster_id(session)
        ws_id_by_name = await get_ws_by_name(session, cluster_id)
        logger.info("  cluster_id=%s", cluster_id)
        logger.info("  workspace: %s", list(ws_id_by_name))

        n = await upsert_quotas(session, cluster_id, ws_id_by_name)
        await session.commit()

        total = await verify_counts(session, cluster_id)
        logger.info("  ✅ upsert %d 条; 表内总计 %d 条", n, total)
        if total == len(QUOTAS):
            logger.info("🎯 配额条数匹配预期 %d", len(QUOTAS))
        else:
            logger.warning("⚠️ 配额条数 %d 与预期 %d 不一致", total, len(QUOTAS))

    await engine.dispose()
    logger.info("完成。")


if __name__ == "__main__":
    asyncio.run(main())
