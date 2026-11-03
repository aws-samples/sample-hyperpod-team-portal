"""Monitoring (Prometheus) Pydantic schemas.

Backend proxies PromQL queries to either:
- In-cluster Prometheus (dev / MVP)
- AWS Managed Prometheus (AMP) via SigV4 (prod)

The response shape matches the Prometheus HTTP API so the frontend can
reuse any standard Prometheus-compatible chart library.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RangeQueryPayload(BaseModel):
    """POST /monitoring/query_range body."""

    query: str = Field(min_length=1, max_length=4096)
    start: float  # unix seconds
    end: float
    step: int = Field(default=15, ge=1, le=3600)  # seconds


class InstantQueryPayload(BaseModel):
    """POST /monitoring/query body."""

    query: str = Field(min_length=1, max_length=4096)
    time: float | None = None  # unix seconds; None = now


# Pass-through Prometheus response shape — we don't restructure samples so
# the frontend can use any prometheus-compatible renderer without wrapping.
class PromResponse(BaseModel):
    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_type: str | None = None
    error: str | None = None


class GpuUtilizationResponse(BaseModel):
    """GET /workspaces/{ws_id}/gpu-utilization 响应.

    avg/max 各一条时序: [[unix_ts, "value%"], ...] (Prom matrix values 原样)。
    空 list = 该时段 team 未占用任何 GPU 卡。
    """

    namespace: str
    days: int
    avg: list[list[Any]] = Field(default_factory=list)
    max: list[list[Any]] = Field(default_factory=list)
    count: list[list[Any]] = Field(default_factory=list)  # 占用 GPU 卡数时序


class QueryTemplate(BaseModel):
    """A named PromQL template with label placeholders for the frontend.

    Placeholders use Prometheus `$var` form (e.g. `namespace="$namespace"`).
    The frontend substitutes before calling `/monitoring/query_range`.
    """

    key: str  # e.g. "gpu_util_by_pod"
    title: str  # 展示标题, 按请求语言从文案表 (monitoring.tpl.<key>.title) 填入; 原始模板里为空串
    unit: str  # "%" | "GiB" | "°C" | "W" | "bytes/s" | "req/s"
    promql: str
    description: str | None = None
    category: Literal[
        "gpu", "cpu", "memory", "disk", "network", "training", "inference", "status",
        "event", "mlflow", "efa", "fsx", "process", "sglang", "dynamo", "ray",
    ]
    # 按请求语言本地化后的分组展示名 (参考 Grafana 面板分区), 由 localize_template 填入; 原始模板里为空。
    group: str | None = None
    # 折叠分组的稳定标识 (slug), 前端按它排序 / 作折叠 key。原始模板可显式指定 (如 Ray), 否则按规则推导。
    group_key: str | None = None
    # 训练任务监控按维度切换:
    #   job      — 聚合到任务级 (一条线 / 一组数字)
    #   pod      — 按 Pod 分线 (DDP 时每 rank 一条)
    #   gpu_card — 按 GPU 卡分线 (每节点 4-8 卡)
    # DevInstance / KPI 不用三维, 留默认即可.
    dimension: Literal["job", "pod", "gpu_card"] = "job"


class KueueQueueRow(BaseModel):
    """一个 workspace 当前的排队情况 (队列页表格一行)。

    active       正常排队, 等前面跑完即可
    inadmissible 请求量超配额或拓扑不满足, 等下去也进不来, 要改任务规格或加配额
    """

    workspace_id: str
    workspace_name: str
    cluster_queue: str
    active: int = 0
    inadmissible: int = 0
