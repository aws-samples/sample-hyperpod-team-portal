from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    # 与 quota/api/schemas.py QuotaModel 同款: 序列化 camelCase 给前端。
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DirQuota(_CamelModel):
    name: str
    gid: int
    pid: int
    used_gib: float
    soft_gib: float
    hard_gib: float
    pct: float


class DirQuotaList(_CamelModel):
    # 列目录接口的返回体: FS 总容量 + 各目录记录 (camelCase → totalGib, directories)
    total_gib: int | None = None
    directories: list[DirQuota]


class CreateDirPayload(_CamelModel):
    # 多 FSx: 指明在哪块盘建目录 (fs-xxxx, 须在 PLATFORM_FSX_FILESYSTEMS 配了)。
    filesystem_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=64)
    hard_gib: int = Field(ge=1, le=1_000_000)
    # 可选复用已有 team 的 gid; 不传则后端自动新分配 (新 team)。
    gid: int | None = Field(default=None, ge=1)


class UpdateQuotaPayload(_CamelModel):
    # 多 FSx: 指明目录在哪块盘。
    filesystem_id: str = Field(min_length=1)
    hard_gib: int = Field(ge=1, le=1_000_000)


class MetricSeries(_CamelModel):
    # {key: [[iso_ts, value], ...]} — key = AWS/FSx 原始 MetricName
    # (FreeDataStorageCapacity / StorageCapacityUtilization / CPUUtilization /
    #  NetworkThroughputUtilization / FileServerDiskThroughputUtilization / DiskIopsUtilization)
    series: dict[str, list[tuple[str, float]]]


class FsxOption(_CamelModel):
    # 监控/配额页下拉框选项: 值 filesystem_id, 展示名 name (AWS Tags[Name])。
    filesystem_id: str
    name: str | None = None
    capacity_gib: int | None = None
