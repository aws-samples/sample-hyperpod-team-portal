"""Workspace 模块种子数据 (§7)

- 3 user (alice/bob/carol)
- 3 workspace 绑到 cluster=hp-cluster-hypd-0507-9390
  * team-a-nlp    owner=alice
  * team-b-vision owner=bob
  * team-c-recsys owner=carol
- 4 membership
  * bob   @ team-a-nlp    developer
  * carol @ team-a-nlp    viewer
  * alice @ team-b-vision admin
  * alice @ team-c-recsys viewer

幂等: email UNIQUE + (cluster_id,name) UNIQUE 兜底 ON CONFLICT DO NOTHING
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
from app.modules.cluster.models import Cluster
from app.modules.user.models import User
from app.modules.workspace.models import UserWorkspaceRole, Workspace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_workspace")


USERS = [
    {"email": "alice@example.com", "display_name": "Alice Chen"},
    {"email": "bob@example.com", "display_name": "Bob Wang"},
    {"email": "carol@example.com", "display_name": "Carol Li"},
]

CLUSTER_TAG = "hp-cluster-hypd-0507-9390"

WORKSPACES = [
    {
        "name": "team-a-nlp",
        "display_name": "Team A — NLP 实验组",
        "description": "NLP 训练 / 大模型微调工作空间",
        "owner_email": "alice@example.com",
    },
    {
        "name": "team-b-vision",
        "display_name": "Team B — Vision 研究",
        "description": "计算机视觉预训练与评测",
        "owner_email": "bob@example.com",
    },
    {
        "name": "team-c-recsys",
        "display_name": "Team C — 推荐算法",
        "description": "推荐系统召回与排序",
        "owner_email": "carol@example.com",
    },
]

MEMBERSHIPS = [
    ("bob@example.com", "team-a-nlp", "developer"),
    ("carol@example.com", "team-a-nlp", "viewer"),
    ("alice@example.com", "team-b-vision", "admin"),
    ("alice@example.com", "team-c-recsys", "viewer"),
]


async def upsert_users(session) -> dict[str, User]:
    """email UNIQUE upsert, 返 email -> User 映射"""
    for row in USERS:
        stmt = pg_insert(User).values(**row, status="active")
        stmt = stmt.on_conflict_do_update(
            index_elements=["email"],
            set_={"display_name": row["display_name"]},
        )
        await session.execute(stmt)
    await session.flush()

    res = await session.execute(select(User).where(User.email.in_([u["email"] for u in USERS])))
    users = list(res.scalars().all())
    by_email = {u.email: u for u in users}
    logger.info("  ✅ User 3 条 upsert 完成: %s", list(by_email))
    return by_email


async def get_cluster_id(session) -> str:
    res = await session.execute(select(Cluster).where(Cluster.cluster_tag == CLUSTER_TAG))
    cluster = res.scalar_one_or_none()
    if cluster is None:
        raise RuntimeError(
            f"cluster '{CLUSTER_TAG}' not seeded — run scripts/seed_data.py first"
        )
    return cluster.id


async def upsert_workspaces(session, cluster_id, users_by_email) -> dict[str, Workspace]:
    for row in WORKSPACES:
        owner = users_by_email[row["owner_email"]]
        payload = {
            "cluster_id": cluster_id,
            "name": row["name"],
            "namespace": row["name"],  # 默认 namespace = name
            "display_name": row["display_name"],
            "description": row["description"],
            "owner_user_id": owner.id,
            "status": "active",
        }
        stmt = pg_insert(Workspace).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["cluster_id", "name"],
            set_={
                "display_name": payload["display_name"],
                "description": payload["description"],
                "namespace": payload["namespace"],
                "owner_user_id": payload["owner_user_id"],
            },
        )
        await session.execute(stmt)
    await session.flush()

    res = await session.execute(
        select(Workspace).where(
            Workspace.cluster_id == cluster_id,
            Workspace.name.in_([w["name"] for w in WORKSPACES]),
        )
    )
    wss = list(res.scalars().all())
    by_name = {w.name: w for w in wss}
    logger.info("  ✅ Workspace 3 条 upsert 完成: %s", list(by_name))
    return by_name


async def upsert_memberships(session, users_by_email, wss_by_name) -> int:
    count = 0
    for email, ws_name, role in MEMBERSHIPS:
        user = users_by_email[email]
        ws = wss_by_name[ws_name]
        stmt = pg_insert(UserWorkspaceRole).values(
            user_id=user.id,
            workspace_id=ws.id,
            role=role,
            invited_by=ws.owner_user_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "workspace_id"],
            set_={"role": role},
        )
        await session.execute(stmt)
        count += 1
    await session.flush()
    logger.info("  ✅ Membership %d 条 upsert 完成", count)
    return count


async def verify_counts(session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, model in (
        ("user", User),
        ("workspace", Workspace),
        ("user_workspace_role", UserWorkspaceRole),
    ):
        res = await session.execute(select(model))
        counts[label] = len(res.scalars().all())
    return counts


async def main() -> None:
    logger.info("开始执行 workspace 种子数据写入 (幂等 upsert)...")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text('SELECT 1 FROM "user" LIMIT 1'))
            await session.execute(text("SELECT 1 FROM workspace LIMIT 1"))
        except Exception as e:
            logger.error(
                "表 user/workspace 未创建 — 请先 `alembic upgrade head`: %s", e
            )
            raise

        cluster_id = await get_cluster_id(session)
        logger.info("  cluster_id=%s (tag=%s)", cluster_id, CLUSTER_TAG)

        users_by_email = await upsert_users(session)
        wss_by_name = await upsert_workspaces(session, cluster_id, users_by_email)
        await upsert_memberships(session, users_by_email, wss_by_name)

        await session.commit()

        counts = await verify_counts(session)
        logger.info("当前表记录数: %s", counts)
        expected = {"user": 3, "workspace": 3, "user_workspace_role": 4}
        if counts == expected:
            logger.info("🎯 全部匹配预期 %s", expected)
        else:
            logger.warning("⚠️ 条数与预期不一致, 预期 %s", expected)

    await engine.dispose()
    logger.info("完成。")


if __name__ == "__main__":
    asyncio.run(main())
