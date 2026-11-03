"""FSx CloudWatch 监控指标路由 (所有登录用户可看, 与工作空间无关)。

配额管理 (建/改/读目录) 仍在 admin router 走超管闸; 监控只读指标独立出来,
挂 get_current_user (任意登录用户即可), 不做 ws 归属校验 —— 监控是全局视图。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.adapters.aws import fsx as fsx_adapter
from app.adapters.aws.cloudwatch import get_fsx_metrics
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.modules.fsx_quota.api.schemas import FsxOption, MetricSeries

logger = get_logger(__name__)

# 任意登录用户可看 (get_current_user, 非 require_admin); 与工作空间无关。
fsx_monitoring_router = APIRouter(
    prefix="/monitoring/fsx",
    tags=["monitoring"],
    dependencies=[Depends(get_current_user)],
)

# range → (窗口秒, period 秒)。1h 用 60s 粒度更细, 6h/24h 用 300s (CW 标准).
_RANGE_MAP = {"1h": (3600, 60), "6h": (21600, 300), "24h": (86400, 300)}


def _range_to_window(rng: str) -> tuple[datetime, datetime, int]:
    span, period = _RANGE_MAP.get(rng, _RANGE_MAP["1h"])
    end = datetime.now(UTC)
    return end - timedelta(seconds=span), end, period


@fsx_monitoring_router.get(
    "/metrics",
    response_model=MetricSeries,
    summary="FSx CloudWatch 指标 (与 console 各 tab 对齐的 6 条原始指标)",
    description=(
        "读取指定 FSx (`filesystem_id`) 的 CloudWatch 时序指标, 供前端监控页趋势图使用.\n\n"
        "**返回结构**: `{series: {<CloudWatch MetricName>: [[iso_ts, value], ...]}}` —— "
        "series 的 key 就是 **AWS/FSx 的原始 MetricName**, 最多 6 条 (与 FSx console 各 tab 对齐):\n"
        "- `FreeDataStorageCapacity` · `StorageCapacityUtilization` (Storage tab, 仅 `FileSystemId` 维度)\n"
        "- `NetworkThroughputUtilization` · `FileServerDiskThroughputUtilization` · `CPUUtilization` "
        "(带额外 `FileServer` 维度)\n"
        "- `DiskIopsUtilization` (带额外 `StorageTargetId` 维度, 只取 `OST` 前缀那条, 排除 MDT)\n\n"
        "**采样**: 两次 CloudWatch 调用 —— 先 `ListMetrics` 探出带额外维度的实际维度值 "
        "(OSS0000 / OST0000 / MDS0000 不写死), 再一次 `GetMetricData` 全部直取 `Average` "
        "(无 metric math). 该 FS 上探不到的指标会**整条缺失** (如未配 MetadataConfiguration), "
        "故实际 key 数可能少于 6.\n\n"
        "`range` 决定窗口 + period (非法值静默回落到 `1h`):\n"
        "- `1h` → 3600s / 60s 粒度 (细看瞬时)\n"
        "- `6h` → 21600s / 300s 粒度\n"
        "- `24h` → 86400s / 300s 粒度 (CW 标准)\n\n"
        "**失败行为**: CloudWatch 调用异常被适配层吞掉, 返回 `200` + `series: {}` (前端退化空图), **不报 5xx**.\n\n"
        "**权限**: 所有登录用户可看 (监控是全局视图, 不做 ws 归属校验).\n"
        "**依赖**: `filesystem_id` 必填 (从 `/monitoring/fsx/filesystems` 列表选); "
        "IAM 需 `cloudwatch:GetMetricData` + `ListMetrics`."
    ),
    responses={
        401: {"description": "未登录"},
        422: {"description": "filesystem_id 缺失 (FastAPI 参数校验)"},
    },
)
async def get_metrics(
    filesystem_id: str = Query(..., description="FSx 文件系统 id (fs-xxxx)"),
    rng: str = Query(default="1h", alias="range"),
) -> dict[str, Any]:
    start, end, period = _range_to_window(rng)
    series = await get_fsx_metrics(filesystem_id, start, end, period)
    return {"series": series}


@fsx_monitoring_router.get(
    "/filesystems",
    response_model=list[FsxOption],
    summary="列可选 FSx (监控/配额下拉用)",
    description=(
        "列平台接入的 FSx, 供前端监控/配额页顶部下拉框选盘。返回 "
        "`{filesystemId, name, capacityGib}` (name = AWS Tags[Name], 拿不到则回落 fs-id)。\n\n"
        "两种模式:\n"
        "- 配了 `PLATFORM_FSX_FILESYSTEMS` → 按配的 fs-id 列表逐个 `DescribeFileSystems`; "
        "**单个不可达只告警跳过, 不整体失败**\n"
        "- 留空 → 全量扫 LUSTRE 文件系统, 按 `Tags[managed]=hyperpod` + `Lifecycle=AVAILABLE` 过滤\n\n"
        "**权限**: 所有登录用户可看。"
    ),
    responses={401: {"description": "未登录"}, 502: {"description": "FSx API 失败"}},
)
async def list_filesystems() -> list[dict[str, Any]]:
    try:
        rows = await fsx_adapter.list_managed_filesystems()
    except fsx_adapter.FsxAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [
        {
            "filesystem_id": r.get("filesystem_id"),
            "name": r.get("name"),
            "capacity_gib": r.get("capacity_gib"),
        }
        for r in rows
    ]
