"""Quota 分配 / 用量解析算法 (纯函数).

把 Kueue ClusterQueue.status 结构和 ComputeQuota 结构翻译成我们的
schema 表达 · 零 IO · 便于 unit test.

设计边界:
- 不调 AWS/K8s 客户端 (那是 orchestration 的活)
- 不碰 DB (那是 persistence 的活, 本模块无独占表)
- 只吃 dict in + 吐 schema out
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.quota.api.schemas import (
    QuotaResourceUsage,
    QuotaUsage,
    TotalsUsage,
)
from app.modules.quota.domain.formulas import (
    ACCELERATOR_RESOURCE_KEYS,
    parse_cpu_cores,
    parse_int_count,
    parse_memory_gib,
)

# ============================================================
# Kueue ClusterQueue.status → QuotaUsage
# ============================================================

def _build_flavor_usage(flavor_entry: dict[str, Any]) -> QuotaResourceUsage:
    """解析 flavorsUsage[] 的单个条目.

    结构 (Kueue v0.12 status):
        {
          "name": "flavor-p4d",
          "resources": [
            {"name": "cpu", "total": "96"},
            {"name": "memory", "total": "1152Gi"},
            {"name": "nvidia.com/gpu", "total": "8"}
          ]
        }
    """
    name = flavor_entry.get("name", "unknown")
    resources = flavor_entry.get("resources") or []
    usage = QuotaResourceUsage(instance_type=name)
    accel = 0
    for r in resources:
        r_name = r.get("name", "")
        # Kueue status 字段名: flavorsUsage/flavorsReservation 都是 `total`
        r_total = r.get("total")
        if r_name == "cpu":
            usage.v_cpu_used = parse_cpu_cores(r_total)
        elif r_name == "memory":
            usage.memory_used_in_gi_b = round(parse_memory_gib(r_total), 3)
        elif r_name in ACCELERATOR_RESOURCE_KEYS:
            accel += parse_int_count(r_total)
    usage.accelerators_used = accel
    return usage


def parse_cluster_queue_status(
    team_name: str, status: dict[str, Any] | None
) -> QuotaUsage:
    """Kueue ClusterQueue.status → QuotaUsage.

    约定:
    - status=None: 返空结果 (resources 空, totals 0)
    - pendingWorkloads 按 flavor 不可拆, 全挂到 totals.accelerators_pending
    - 优先用 flavorsUsage (实际 admit 占用), 次选 flavorsReservation
    """
    now = datetime.now(UTC)
    if not status:
        return QuotaUsage(
            team_name=team_name,
            resources=[],
            totals=TotalsUsage(),
            captured_at=now,
        )

    flavors = status.get("flavorsUsage") or status.get("flavorsReservation") or []
    resources: list[QuotaResourceUsage] = []
    totals_accel = 0
    totals_cpu = 0.0
    totals_mem = 0.0
    for entry in flavors:
        u = _build_flavor_usage(entry)
        resources.append(u)
        totals_accel += u.accelerators_used
        totals_cpu += u.v_cpu_used
        totals_mem += u.memory_used_in_gi_b

    pending = parse_int_count(status.get("pendingWorkloads"))
    totals = TotalsUsage(
        accelerators=totals_accel,
        accelerators_pending=pending,
        v_cpu=round(totals_cpu, 3),
        memory_in_gi_b=round(totals_mem, 3),
    )

    return QuotaUsage(
        team_name=team_name,
        resources=resources,
        totals=totals,
        captured_at=now,
    )
