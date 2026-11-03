#!/usr/bin/env python3
"""一次性运维: 给存量活跃行回填顶层 active_ws (进稀疏 GSI active-index)。

背景:
    稀疏 GSI active-index (PK=active_ws, SK=created_at) 上线后, 新写入的活跃行
    (kueue_status in {queued, started}) 会带顶层 active_ws=workspace_id 属性, 自动进 GSI。
    但 GSI 上线前已存在的活跃行没有 active_ws 属性 → 不进 GSI → 任务总览漏显。
    本脚本扫 ResourceIndex 全表, 给"活跃 + 无 deleted_at + 无 active_ws"的存量行
    补 active_ws=workspace_id, 使其进 GSI。

幂等:
    回填条件含 not item.get("active_ws"), 已带 active_ws 的行跳过; 重跑安全。
    update_item 表达式仅 SET active_ws, 不动其它字段。

用法:
    cd services/platform-api
    # 干跑 (只打印待回填, 不写):
    DDB_TABLE_PREFIX=hypd-dev AWS_REGION=us-west-2 \
        .venv/bin/python scripts/backfill-active-ws.py --dry-run
    # 真写:
    DDB_TABLE_PREFIX=hypd-dev AWS_REGION=us-west-2 \
        .venv/bin/python scripts/backfill-active-ws.py

    DDB Local 模式额外设 DDB_ENDPOINT_URL=http://localhost:8000 (走 dummy 凭证)。

环境变量 (沿用 app.core.config 同套, 与后端启动命令一致):
    DDB_TABLE_PREFIX 表名前缀 (如 hypd-dev), 决定 tables.RESOURCE_INDEX_TABLE
    AWS_REGION 区域 (如 us-west-2)
    AWS_PROFILE 凭证 profile (真 AWS 时)
    DDB_ENDPOINT_URL  DDB Local 端点 (可选)

依赖 app 模块: app.adapters.ddb.{base, tables, client}。
用到的 DDB 接口:
    - tables.RESOURCE_INDEX_TABLE 表名常量
    - client.ddb_resource() async context manager 拿 Table, 直接 table.scan 翻页
                                            (base.scan_all 注释禁 ResourceIndex 全表扫; 一次性运维
                                             可直接翻页, 不走 scan_all)
    - base.update_item(table, key, update_expression, expression_values) 部分更新 SET active_ws
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from app.adapters.ddb import base, tables
from app.adapters.ddb.client import ddb_resource
from app.modules.shared.kueue_status import is_active


async def _scan_resource_index() -> list[dict[str, Any]]:
    """全表翻页扫 ResourceIndex (一次性运维; 不走 base.scan_all 因其禁 ResourceIndex)。"""
    items: list[dict[str, Any]] = []
    last_key: dict[str, Any] | None = None
    async with ddb_resource() as ddb:
        table = await ddb.Table(tables.RESOURCE_INDEX_TABLE)
        while True:
            kwargs: dict[str, Any] = {}
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = await table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
    return items


def _needs_backfill(item: dict[str, Any]) -> bool:
    """活跃 (shared.is_active: 六态除Finished + 存量旧值) 且无 deleted_at 且无 active_ws → 待回填。"""
    md = item.get("metadata") or {}
    if not is_active(md.get("kueue_status")):
        return False
    if item.get("deleted_at"):
        return False
    if item.get("active_ws"):
        return False
    return True


async def backfill(dry_run: bool) -> int:
    items = await _scan_resource_index()
    print(f"扫描 ResourceIndex 共 {len(items)} 行, 表={tables.RESOURCE_INDEX_TABLE}")

    targets = [it for it in items if _needs_backfill(it)]
    print(f"待回填 (活跃 + 无 deleted_at + 无 active_ws): {len(targets)} 行")

    written = 0
    for it in targets:
        workspace_id = it["workspace_id"]
        resource_key = it["resource_key"]
        md = it.get("metadata") or {}
        kueue_status = md.get("kueue_status")
        if dry_run:
            print(
                f"  [dry-run] ws={workspace_id} resource_key={resource_key} "
                f"kueue_status={kueue_status} -> active_ws={workspace_id}"
            )
            continue
        # 部分更新: 仅 SET active_ws=workspace_id (顶层属性进稀疏 GSI)。
        # require_exists=True (默认): 行必然存在 (刚扫出来), attribute_exists 保护即可。
        await base.update_item(
            tables.RESOURCE_INDEX_TABLE,
            {"workspace_id": workspace_id, "resource_key": resource_key},
            "SET active_ws = :w",
            {":w": workspace_id},
        )
        written += 1
        print(
            f"  [写入] ws={workspace_id} resource_key={resource_key} "
            f"-> active_ws={workspace_id}"
        )

    if dry_run:
        print(f"干跑完成: 待回填 {len(targets)} 行 (未写)。")
    else:
        print(f"回填完成: 已写 {written} 行。")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="存量活跃行回填 active_ws (进稀疏 GSI active-index, 幂等, 一次性运维)。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印待回填行, 不写 DDB。",
    )
    args = parser.parse_args()
    asyncio.run(backfill(args.dry_run))


if __name__ == "__main__":
    main()
