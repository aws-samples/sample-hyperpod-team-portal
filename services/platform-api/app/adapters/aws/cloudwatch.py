"""CloudWatch 指标异步客户端 (aioboto3) — FSx for Lustre 监控指标。

client 复用模式与 cloudwatch_logs.py 一致 (进程内共享 + AsyncExitStack)。
拉取与 AWS FSx console 各 tab 一致的 metric (Storage / Performance / Metadata)。
带额外维度 (FileServer / StorageTargetId) 的 metric 先 list_metrics 探实际维度值
再拉, 维度值不写死 (不同 FS 编号可能不同)。
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

import aioboto3

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_cw_client: Any | None = None
_cw_client_stack: AsyncExitStack | None = None
_cw_client_lock = asyncio.Lock()


async def _get_cw_client() -> Any:
    global _cw_client, _cw_client_stack
    if _cw_client is not None:
        return _cw_client
    async with _cw_client_lock:
        if _cw_client is not None:
            return _cw_client
        settings = get_settings()
        if settings.aws_profile:
            session = aioboto3.Session(profile_name=settings.aws_profile)
        else:
            session = aioboto3.Session()
        stack = AsyncExitStack()
        client = await stack.enter_async_context(
            session.client("cloudwatch", region_name=settings.aws_region)
        )
        _cw_client_stack = stack
        _cw_client = client
        return _cw_client


async def aclose_cw_client() -> None:
    global _cw_client, _cw_client_stack
    if _cw_client_stack is not None:
        await _cw_client_stack.aclose()
    _cw_client = None
    _cw_client_stack = None


# 与 AWS FSx console 各 tab 展示的 metric 完全对齐。console 里这些不是原始计数,
# 而是 Utilization 百分比 / 容量 metric, 且带额外维度 (FileServer / StorageTargetId)。
# 维度值 (OSS0000 / OST0000 / MDS0000...) 不写死 —— 先 list_metrics 探实际值再拉,
# 不同 FS 编号可能不同。key = MetricName (前端标题用 console 显示名, 见前端映射)。
#
# spec 字段: key(=后端返回的 series 键) / metric / stat / extra(额外维度名, None=仅
# FileSystemId) / value_prefix(同名 metric 多个额外维度值时按前缀选, 如 Disk IOPS 取
# OST 排除 MDT)。
_FSX_METRIC_SPECS: list[dict[str, Any]] = [
    # Storage tab
    {"key": "FreeDataStorageCapacity", "metric": "FreeDataStorageCapacity",
     "stat": "Average", "extra": None},
    {"key": "StorageCapacityUtilization", "metric": "StorageCapacityUtilization",
     "stat": "Average", "extra": None},
    # Performance tab (Object storage performance)
    {"key": "NetworkThroughputUtilization", "metric": "NetworkThroughputUtilization",
     "stat": "Average", "extra": "FileServer"},
    {"key": "FileServerDiskThroughputUtilization", "metric": "FileServerDiskThroughputUtilization",
     "stat": "Average", "extra": "FileServer"},
    {"key": "DiskIopsUtilization", "metric": "DiskIopsUtilization",
     "stat": "Average", "extra": "StorageTargetId", "value_prefix": "OST"},
    # Metadata performance
    {"key": "CPUUtilization", "metric": "CPUUtilization",
     "stat": "Average", "extra": "FileServer"},
]


def resolve_query_specs(
    fs_id: str, listed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """结合 list_metrics 结果解析出每条 query 的实际维度 (纯函数, 便于单测)。

    listed: list_metrics 返回的 Metrics (每项含 MetricName + Dimensions)。
    返回 [{id, key, metric, stat, dimensions}] —— id 是小写别名 mN
    (get_metric_data 的 Id 规则 ^[a-z]...); dimensions 含 FileSystemId + 额外维度。
    探不到额外维度的 spec 跳过 (该 FS 无此指标, 如未配 MetadataConfiguration)。
    """
    fs_dim = {"Name": "FileSystemId", "Value": fs_id}
    resolved: list[dict[str, Any]] = []
    idx = 0
    for spec in _FSX_METRIC_SPECS:
        if spec["extra"] is None:
            resolved.append({
                "id": f"m{idx}", "key": spec["key"], "metric": spec["metric"],
                "stat": spec["stat"], "dimensions": [fs_dim],
            })
            idx += 1
            continue
        # 带额外维度: 从 list_metrics 里找该 metric 的实际维度组合
        for m in listed:
            if m.get("MetricName") != spec["metric"]:
                continue
            dims = m.get("Dimensions") or []
            extra_val = next(
                (d["Value"] for d in dims if d.get("Name") == spec["extra"]), None
            )
            if extra_val is None:
                continue
            if spec.get("value_prefix") and not extra_val.startswith(spec["value_prefix"]):
                continue
            resolved.append({
                "id": f"m{idx}", "key": spec["key"], "metric": spec["metric"],
                "stat": spec["stat"], "dimensions": dims,
            })
            idx += 1
            break  # 每个 spec 只取第一个匹配 (单 OSS/OST/MDS)
    return resolved


def build_metric_queries(resolved: list[dict[str, Any]], period: int) -> list[dict[str, Any]]:
    """按 resolve_query_specs 的结果拼 get_metric_data queries (全部直取)。"""
    return [
        {
            "Id": spec["id"],
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/FSx",
                    "MetricName": spec["metric"],
                    "Dimensions": spec["dimensions"],
                },
                "Period": period,
                "Stat": spec["stat"],
            },
        }
        for spec in resolved
    ]


def parse_metric_results(
    results: list[dict[str, Any]], id_to_key: dict[str, str]
) -> dict[str, list[tuple[str, float]]]:
    """boto MetricDataResults → {series key: [(iso_ts, value)]}。

    id_to_key: query Id (mN) → series key (metric 名)。Timestamps 是 datetime,
    转 ISO 字符串 (schema 要 str)。
    """
    out: dict[str, list[tuple[str, float]]] = {}
    for r in results:
        rid = r.get("Id", "")
        key = id_to_key.get(rid, rid)
        ts = r.get("Timestamps") or []
        vals = r.get("Values") or []
        out[key] = [
            (t.isoformat() if hasattr(t, "isoformat") else str(t), float(v))
            for t, v in zip(ts, vals)
        ]
    return out


async def get_fsx_metrics(
    fs_id: str, start: datetime, end: datetime, period: int
) -> dict[str, list[tuple[str, float]]]:
    """拉 FSx 监控指标 (与 console 各 tab 对齐)。失败返空 dict (前端退化)。

    先 list_metrics 探带额外维度 metric 的实际维度值, 再 get_metric_data。
    """
    cw = await _get_cw_client()
    try:
        listed_resp = await cw.list_metrics(
            Namespace="AWS/FSx",
            Dimensions=[{"Name": "FileSystemId", "Value": fs_id}],
        )
        listed = listed_resp.get("Metrics", []) or []
        resolved = resolve_query_specs(fs_id, listed)
        id_to_key = {spec["id"]: spec["key"] for spec in resolved}
        resp = await cw.get_metric_data(
            StartTime=start,
            EndTime=end,
            MetricDataQueries=build_metric_queries(resolved, period),
            ScanBy="TimestampAscending",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cloudwatch.get_fsx_metrics.fail", fs_id=fs_id, err=str(exc))
        return {}
    return parse_metric_results(resp.get("MetricDataResults", []) or [], id_to_key)
