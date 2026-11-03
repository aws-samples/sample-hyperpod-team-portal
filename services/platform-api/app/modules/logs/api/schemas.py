"""Log-tail / CloudWatch Logs Insights schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LogLine(BaseModel):
    """One log line delivered to the frontend.

    `message` is the raw application log (Fluent Bit `log` field), with the
    surrounding Kubernetes JSON envelope already stripped by the backend.
    """

    timestamp_ms: int  # unix millis
    message: str
    stream: Literal["stdout", "stderr", "agent"] = "stdout"
    pod: str | None = None
    container: str | None = None
    node: str | None = None


class LogResponse(BaseModel):
    """Payload for GET /training-jobs/{id}/logs."""

    lines: list[LogLine] = Field(default_factory=list)
    # Next `since_ms` the frontend should pass on poll to avoid duplicates.
    next_since_ms: int | None = None
    # When True, something upstream said "too early" (pod just scheduled, no
    # logs yet, Insights query still starting). UI keeps polling.
    warming_up: bool = False
    # Surface backend-side notice (e.g. "using pod exec fallback") so the UI
    # can render a subtle banner instead of appearing silent.
    source: Literal["cloudwatch", "pod_exec", "none"] = "cloudwatch"


# ===== 历史日志 (完成/报错 task · CloudWatch get_log_events) =====


class HistoryStreamInfo(BaseModel):
    """一个 trainer stream = 前端一个 tab。"""

    stream_name: str
    pod_name: str = ""  # 完整 pod 名 (前端下拉显示, 从抽屉跳来时能认出); 老缓存可能缺→默认空
    pod_short: str
    seq: int
    first_ts: int
    last_ts: int


class HistoryLogLine(BaseModel):
    """历史日志单行 (3 字段)。"""

    time: str
    stream: Literal["stdout", "stderr"] = "stdout"
    log: str


class HistoryLogPage(BaseModel):
    """单 stream 一页日志。

    两种翻页语义:
    - browse (GetLogEvents): 同屏双向。定位最新后, forward_token 往更新翻 (下滑),
      backward_token 往更早翻 (上滑)。运行中任务下滑即可拉到新日志 (~30s CW 延迟)。
    - search (FilterLogEvents): 单向旧→新, 只用 next_token (下滑加载更新)。

    前端按 mode 取对应 token: browse 用 forward_token/backward_token, search 用 next_token。
    """

    lines: list[HistoryLogLine] = Field(default_factory=list)
    # search 态单向游标 (旧→新)
    next_token: str | None = None
    # browse 态双向游标: 往更新 / 往更早
    forward_token: str | None = None
    backward_token: str | None = None
    # "browse" = GetLogEvents 同屏双向; "search" = FilterLogEvents 单向 (旧→新)。
    mode: Literal["browse", "search"] = "browse"


# ===== 整任务搜索 (跨所有 pod · Logs Insights) =====


class WholeTaskLogLine(BaseModel):
    """整任务搜索单行: 比历史单行多 pod 来源 (跨 pod 混排需标出自哪个 pod)。"""

    time: str  # Insights @timestamp 字符串 (UTC)
    stream: Literal["stdout", "stderr"] = "stdout"
    log: str
    pod: str = ""  # 来源 pod 名 (信封 kubernetes.pod_name)


class WholeTaskSearchResult(BaseModel):
    """整任务搜索结果 (Insights 一次性返回, 无翻页)。

    Insights 单查返回上限 = limit (≤10000)。命中达 limit 视为被截断
    (truncated=True), 前端提示"结果过多, 请缩小时间窗或加关键字"。
    """

    lines: list[WholeTaskLogLine] = Field(default_factory=list)
    truncated: bool = False
