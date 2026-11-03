"""队列页表格数据: 一次拿全部可见 workspace 的当前排队数。

与 templates.py 的分工: 那边只渲 PromQL 字符串给前端自己查; 这里要跨 ws 聚合,
故后端直接发一次 instant query 再按 cluster_queue 归组。

ClusterQueue 名 = <namespace>-clusterqueue (建 workspace 时同步创建)。
"""

from __future__ import annotations

from typing import Any

from app.adapters.prometheus import PromAPIError
from app.adapters.prometheus import instant_query as prom_instant_query
from app.core.logging import get_logger
from app.modules.monitoring.api.schemas import KueueQueueRow

logger = get_logger(__name__)

# 不带 cluster_queue 过滤: 一次取回全部队列的 series, 再在内存里按 ws 归组
_PENDING_QUERY = "kueue_pending_workloads"

_STATUS_ACTIVE = "active"
_STATUS_INADMISSIBLE = "inadmissible"


def _parse_counts(prom_body: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Prom instant 响应 → {cluster_queue: {status: count}}。

    value 形如 [1785900000, "3"], 计数是字符串; 解不出来当 0, 不让脏 series 崩掉整表。
    """
    out: dict[str, dict[str, int]] = {}
    for series in (prom_body.get("data") or {}).get("result") or []:
        metric = series.get("metric") or {}
        cq = metric.get("cluster_queue")
        st = metric.get("status")
        if not cq or not st:
            continue
        raw = (series.get("value") or [None, "0"])[-1]
        try:
            n = int(float(raw))
        except (TypeError, ValueError):
            n = 0
        out.setdefault(cq, {})[st] = n
    return out


async def list_kueue_queue_rows(
    workspaces: list[dict[str, Any]],
) -> list[KueueQueueRow]:
    """给定可见 ws 列表, 返回每个 ws 的 active / inadmissible。

    AMP 查不通时不抛错, 全部按 0 返回 —— 表格结构比数字重要, 先让页面能开。
    没有 namespace 的 ws 跳过 (建到一半的空壳)。
    """
    try:
        counts = _parse_counts(await prom_instant_query(_PENDING_QUERY))
    except PromAPIError as exc:
        logger.info("kueue_queues.prom_err", code=exc.status_code)
        counts = {}

    rows: list[KueueQueueRow] = []
    for ws in workspaces:
        ns = ws.get("namespace") or (ws.get("metadata_json") or {}).get("namespace")
        if not ns:
            continue
        cq = f"{ns}-clusterqueue"
        c = counts.get(cq) or {}
        rows.append(
            KueueQueueRow(
                workspace_id=str(ws.get("id") or ""),
                workspace_name=ws.get("display_name") or ws.get("name") or "",
                cluster_queue=cq,
                active=c.get(_STATUS_ACTIVE, 0),
                inadmissible=c.get(_STATUS_INADMISSIBLE, 0),
            )
        )
    # inadmissible 排前 (要人处理的), 再 active, 最后按名字保持稳定顺序
    rows.sort(key=lambda r: (-r.inadmissible, -r.active, r.workspace_name))
    return rows
