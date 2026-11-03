"""Wipe seed 假数据,保留 cluster 元数据(但重置 state=Unknown + last_synced_at=NULL).

用途:在跑真实 sync 前清桌面.
幂等: 可反复跑.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import AsyncSessionLocal


async def _main() -> None:
    async with AsyncSessionLocal() as db:
        # 顺序: 先删 child,最后删 quota,cluster 不删
        await db.execute(text("DELETE FROM node_status"))
        await db.execute(text("DELETE FROM instance_group"))
        await db.execute(text("DELETE FROM resource_quota"))
        await db.execute(
            text("UPDATE cluster SET state = 'Unknown', last_synced_at = NULL")
        )
        await db.commit()
        print("[wipe_seed] cleared node_status / instance_group / resource_quota")
        print("[wipe_seed] reset cluster.state=Unknown, last_synced_at=NULL")


if __name__ == "__main__":
    asyncio.run(_main())
