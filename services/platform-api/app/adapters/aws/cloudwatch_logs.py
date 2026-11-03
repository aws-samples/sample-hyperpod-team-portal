"""CloudWatch Logs Insights 异步客户端 (aioboto3).

职责 (仅此，不含业务逻辑):
    - 启动 Insights 查询
    - 轮询拿结果
    - 区分 ResourceNotFoundException (log group 不存在) 和其它失败

业务侧 (app/modules/logs) 负责:
    - 构造 query string
    - 解析 event 字段为 LogLine
    - 判断 warming_up
"""

from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from typing import Any

import aioboto3

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---- 进程内共享 logs client (复用连接池, 消除每次调用新建 client 的开销) ----
# aioboto3 client 是 async context manager, 用 AsyncExitStack 在首次调用时 enter
# 一次并缓存, 进程存活期间复用 (连接池 keep-alive), shutdown 时 aclose 统一关闭。
# 无状态 + 线程/协程安全, 全进程共享 1 个最划算 (与 ddb/client.py 同理念)。
_logs_client: Any | None = None
_logs_client_stack: AsyncExitStack | None = None
_logs_client_lock = asyncio.Lock()


async def _get_logs_client() -> Any:
    """返回进程内共享的 logs client (lazy 首次构造, 之后复用)。"""
    global _logs_client, _logs_client_stack
    if _logs_client is not None:
        return _logs_client
    async with _logs_client_lock:
        if _logs_client is not None:  # 双检: 等锁期间别的协程已建好
            return _logs_client
        settings = get_settings()
        client_kwargs: dict[str, Any] = {"region_name": settings.aws_region}
        if settings.aws_profile:
            session = aioboto3.Session(profile_name=settings.aws_profile)
        else:
            session = aioboto3.Session()
        stack = AsyncExitStack()
        client = await stack.enter_async_context(
            session.client("logs", **client_kwargs)
        )
        _logs_client_stack = stack
        _logs_client = client
        return _logs_client


async def aclose_logs_client() -> None:
    """进程 shutdown 时关闭共享 client (释放连接池)。测试可用于重置。"""
    global _logs_client, _logs_client_stack
    if _logs_client_stack is not None:
        await _logs_client_stack.aclose()
    _logs_client = None
    _logs_client_stack = None

# Insights 查询: start_query 立即返回, get_query_results 需轮询.
# <10k 事件 10s 内足够, status == Complete 时提前短路.
_MAX_QUERY_SECONDS = 10
_POLL_INTERVAL_SECONDS = 0.5


class LogGroupNotFoundError(Exception):
    """CloudWatch log group 不存在 (通常是 HyperPod observability add-on 没装)."""

    def __init__(self, log_group: str) -> None:
        self.log_group = log_group
        super().__init__(
            f"CloudWatch log group not found: {log_group}. "
            "Is the HyperPod observability add-on installed?"
        )


class InvalidPageTokenError(Exception):
    """翻页 token 非法 (常见: 浏览态 GetLogEvents 的 token 误传给 FilterLogEvents,
    或反之 — 两者 token 格式不通用; 也可能 token 已过期 24h)。前端应清空 token 重查。"""

    def __init__(self, message: str = "invalid page token") -> None:
        super().__init__(message)


async def run_insights_query(
    *,
    log_group: str,
    start_ms: int,
    end_ms: int,
    query: str,
    limit: int,
    max_seconds: float = _MAX_QUERY_SECONDS,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
) -> list[list[dict[str, Any]]]:
    """Run a Logs Insights query and return raw ``results`` list.

    返回 Insights 原始格式: ``list[list[{"field": str, "value": str}]]``;
    上层按字段 dict 化后再做领域解析.

    Timeouts (可覆盖; 默认 10s/0.5s 适合实时日志快响应; 整任务搜索扫描量大传 30s/1s):
        - start_query 立即返回 (失败直接抛 ResourceNotFoundException).
        - get_query_results 轮询 ``max_seconds`` 秒, 超时返回当前累积结果.
    """
    logs = await _get_logs_client()
    try:
        resp = await logs.start_query(
            logGroupName=log_group,
            startTime=int(start_ms / 1000),
            endTime=int(end_ms / 1000),
            queryString=query,
            limit=limit,
        )
    except logs.exceptions.ResourceNotFoundException as exc:
        logger.info(
            "cloudwatch_logs.start_query.group_missing",
            log_group=log_group,
        )
        raise LogGroupNotFoundError(log_group) from exc

    query_id = resp["queryId"]
    deadline = time.monotonic() + max_seconds
    results_raw: list[list[dict[str, Any]]] = []
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)
        r = await logs.get_query_results(queryId=query_id)
        status = r.get("status")
        if status == "Complete":
            results_raw = r.get("results", []) or []
            break
        if status in ("Failed", "Cancelled", "Timeout"):
            logger.warning(
                "cloudwatch_logs.query.non_success",
                status=status,
                query_id=query_id,
            )
            break

    return results_raw


async def describe_log_streams_by_prefix(
    *, log_group: str, prefix: str
) -> list[dict[str, Any]]:
    """列出 log_group 下名字以 prefix 开头的所有 stream (翻页取全)。

    log group 不存在 → 抛 LogGroupNotFoundError (与 run_insights_query 一致)。
    """
    logs = await _get_logs_client()
    out: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "logGroupName": log_group,
            "logStreamNamePrefix": prefix,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        try:
            resp = await logs.describe_log_streams(**kwargs)
        except logs.exceptions.ResourceNotFoundException as exc:
            raise LogGroupNotFoundError(log_group) from exc
        out.extend(resp.get("logStreams", []) or [])
        next_token = resp.get("nextToken")
        if next_token is None:
            break
    return out


async def get_log_events(
    *,
    log_group: str,
    stream: str,
    start_from_head: bool,
    next_token: str | None,
    limit: int,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> dict[str, Any]:
    """读单个 stream 一页日志。返回 {events, next_forward_token, next_backward_token}。

    双向翻页: nextForwardToken (往新翻) + nextBackwardToken (往旧翻)。start_ms/end_ms
    可选时间窗过滤 (GetLogEvents 原生支持, 且保留双向 token — 故纯时间筛选走此接口
    即可保住排序; 只有内容搜索才必须用 filter_log_events)。
    """
    logs = await _get_logs_client()
    kwargs: dict[str, Any] = {
        "logGroupName": log_group,
        "logStreamName": stream,
        "startFromHead": start_from_head,
        "limit": limit,
    }
    if start_ms is not None:
        kwargs["startTime"] = start_ms
    if end_ms is not None:
        kwargs["endTime"] = end_ms
    if next_token:
        kwargs["nextToken"] = next_token
    try:
        resp = await logs.get_log_events(**kwargs)
    except logs.exceptions.ResourceNotFoundException as exc:
        raise LogGroupNotFoundError(log_group) from exc
    return {
        "events": resp.get("events", []) or [],
        "next_forward_token": resp.get("nextForwardToken"),
        "next_backward_token": resp.get("nextBackwardToken"),
    }


async def filter_log_events(
    *,
    log_group: str,
    stream: str,
    filter_pattern: str,
    start_ms: int | None,
    end_ms: int | None,
    next_token: str | None,
    limit: int,
) -> dict[str, Any]:
    """在单个 stream 内按 filterPattern + 时间窗过滤一页日志 (恒旧→新)。

    结果按时间升序 (旧→新), 单个 nextToken 只能往更新方向翻。
    ⚠️ 为什么不做"新→旧": FilterLogEvents 的 startFromHead=false 在
    "单 stream + filterPattern/时间窗"组合下首页返回空 events (仅带 nextToken,
    要翻很多页才见数据), 体验远差于 startFromHead=true 的秒回 (实测 2026-07-07)。
    故搜索态只用默认正序; 双向浏览走 GetLogEvents。
    filter_pattern 为空串 = 仅按时间窗过滤。

    返回 {events, next_token}。空 events + 非空 next_token 表示"这段扫完没命中,
    还有下一段"—— 是否翻完只看 next_token (不能看 events 是否空)。
    """
    logs = await _get_logs_client()
    kwargs: dict[str, Any] = {
        "logGroupName": log_group,
        "logStreamNames": [stream],
        "limit": limit,
    }
    if filter_pattern:
        kwargs["filterPattern"] = filter_pattern
    if start_ms is not None:
        kwargs["startTime"] = start_ms
    if end_ms is not None:
        kwargs["endTime"] = end_ms
    if next_token:
        kwargs["nextToken"] = next_token
    try:
        resp = await logs.filter_log_events(**kwargs)
    except logs.exceptions.ResourceNotFoundException as exc:
        raise LogGroupNotFoundError(log_group) from exc
    except logs.exceptions.InvalidParameterException as exc:
        # 最常见: 传了 GetLogEvents 的 token (浏览↔搜索切换未清 token);
        # 或 start_from_head=False 但时间窗早于 2024-01-01。
        raise InvalidPageTokenError(str(exc)) from exc
    return {
        "events": resp.get("events", []) or [],
        "next_token": resp.get("nextToken"),
    }
