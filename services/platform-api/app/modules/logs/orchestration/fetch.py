"""训练任务日志拉取业务流.

Pipeline (verified 2026-05-11):
    1. HyperPod observability add-on -> Fluent Bit DaemonSet
    2. Fluent Bit tails /var/log/containers/*.log -> CloudWatch log group
    3. We call Logs Insights with a UUID string-match query
    4. Parse Fluent Bit JSON envelopes into LogLine

Insights 有冷启动延迟 (~1-5s) 和单次结果上限 (10k 事件); 训练日志 tab
只需 "最近 N 行 + 轮询", 单次同步 ``start_query -> get_query_results``
够用. WebSocket live tail 留到 M4.
"""

from __future__ import annotations

import time

from app.adapters.aws.cloudwatch_logs import (
    LogGroupNotFoundError,
    run_insights_query,
)
from app.core.logging import get_logger
from app.modules.logs.api.schemas import LogLine, WholeTaskLogLine, WholeTaskSearchResult
from app.modules.logs.domain.event_parsing import parse_insights_event
from app.modules.logs.domain.insights_query import (
    build_devinstance_whole_search_query,
    build_dynamo_whole_search_query,
    build_inference_whole_search_query,
    build_llmd_whole_search_query,
    build_ray_whole_search_query,
    build_training_job_query,
    build_whole_task_search_query,
)
from app.modules.logs.domain.log_group_naming import build_log_group

logger = get_logger(__name__)


class LogsServiceError(Exception):
    """业务层统一异常 (暴露给 router 转 502)."""


# 整任务搜索默认时间窗 (无显式起点时): 近 24h。Insights 按扫描量计费, 不宜无边界。
_WHOLE_TASK_DEFAULT_WINDOW_MS = 24 * 60 * 60 * 1000
# 单查返回上限 (= 截断阈值)。命中达此数视为被截断。
_WHOLE_TASK_LIMIT = 10000


async def search_whole_task_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    training_job_id: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
) -> WholeTaskSearchResult:
    """整任务 (跨所有 pod) 搜索, 走 Logs Insights。

    - 用 @message like "<job_id>" 圈定整任务 (不枚举 stream); 只 trainer 容器。
    - query 空 = 整任务全部; 有 = 按 log 字段关键字/正则过滤。
    - 时间窗: 未给起点默认近 24h; 未给终点默认 now。
    - 命中达 _WHOLE_TASK_LIMIT → truncated=True (前端提示缩小范围)。
    """
    import time as _time

    log_group = build_log_group(cluster_tag, cluster_arn)
    now_ms = int(_time.time() * 1000)
    end = end_ms if end_ms is not None else now_ms
    start = start_ms if start_ms is not None else end - _WHOLE_TASK_DEFAULT_WINDOW_MS

    q = build_whole_task_search_query(
        training_job_id=training_job_id,
        query=query,
        is_regex=is_regex,
        limit=_WHOLE_TASK_LIMIT,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start,
            end_ms=end,
            query=q,
            limit=_WHOLE_TASK_LIMIT,
            # 整任务扫描量大, 给更长超时 + 每秒轮询一次 (实时日志仍用默认 10s/0.5s)
            max_seconds=30,
            poll_interval=1.0,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    # query 直接 select 了 @timestamp/@logStream/log/stream (Insights 已自动解析
    # Fluent Bit JSON 信封, log/stream 即正文/流)。逐行按字段名取, 不再解 @message。
    lines: list[WholeTaskLogLine] = []
    for ev in results_raw:
        by = {f["field"]: f["value"] for f in ev}
        stream = by.get("stream", "stdout")
        if stream not in ("stdout", "stderr"):
            stream = "stdout"
        lines.append(
            WholeTaskLogLine(
                time=str(by.get("@timestamp", "")),
                stream=stream,
                log=str(by.get("log", "")).rstrip("\n"),
                pod=_pod_from_log_stream(by.get("@logStream", "")),
            )
        )
    return WholeTaskSearchResult(
        lines=lines, truncated=len(results_raw) >= _WHOLE_TASK_LIMIT
    )


async def search_whole_inference_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    endpoint_name: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
) -> WholeTaskSearchResult:
    """推理整任务 (跨该 endpoint 所有 pod) 搜索, 走 Logs Insights。

    与 search_whole_task_logs 同构, 仅圈定方式不同 (endpoint stream 前缀,
    见 build_inference_whole_search_query)。
    """
    import time as _time

    log_group = build_log_group(cluster_tag, cluster_arn)
    now_ms = int(_time.time() * 1000)
    end = end_ms if end_ms is not None else now_ms
    start = start_ms if start_ms is not None else end - _WHOLE_TASK_DEFAULT_WINDOW_MS

    q = build_inference_whole_search_query(
        endpoint_name=endpoint_name,
        query=query,
        is_regex=is_regex,
        limit=_WHOLE_TASK_LIMIT,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start,
            end_ms=end,
            query=q,
            limit=_WHOLE_TASK_LIMIT,
            max_seconds=30,
            poll_interval=1.0,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[WholeTaskLogLine] = []
    for ev in results_raw:
        by = {f["field"]: f["value"] for f in ev}
        stream = by.get("stream", "stdout")
        if stream not in ("stdout", "stderr"):
            stream = "stdout"
        lines.append(
            WholeTaskLogLine(
                time=str(by.get("@timestamp", "")),
                stream=stream,
                log=str(by.get("log", "")).rstrip("\n"),
                pod=_pod_from_log_stream(by.get("@logStream", "")),
            )
        )
    return WholeTaskSearchResult(
        lines=lines, truncated=len(results_raw) >= _WHOLE_TASK_LIMIT
    )


async def search_whole_dynamo_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    k8s_cr_name: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
) -> WholeTaskSearchResult:
    """Dynamo 整任务 (跨 frontend + 所有 worker pod) 搜索, 走 Logs Insights。

    与 search_whole_inference_logs 同构, 仅圈定方式不同 (CR 名 stream 前缀 +
    主容器固定 "main", 见 build_dynamo_whole_search_query)。
    """
    import time as _time

    log_group = build_log_group(cluster_tag, cluster_arn)
    now_ms = int(_time.time() * 1000)
    end = end_ms if end_ms is not None else now_ms
    start = start_ms if start_ms is not None else end - _WHOLE_TASK_DEFAULT_WINDOW_MS

    q = build_dynamo_whole_search_query(
        k8s_cr_name=k8s_cr_name,
        query=query,
        is_regex=is_regex,
        limit=_WHOLE_TASK_LIMIT,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start,
            end_ms=end,
            query=q,
            limit=_WHOLE_TASK_LIMIT,
            max_seconds=30,
            poll_interval=1.0,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[WholeTaskLogLine] = []
    for ev in results_raw:
        by = {f["field"]: f["value"] for f in ev}
        stream = by.get("stream", "stdout")
        if stream not in ("stdout", "stderr"):
            stream = "stdout"
        lines.append(
            WholeTaskLogLine(
                time=str(by.get("@timestamp", "")),
                stream=stream,
                log=str(by.get("log", "")).rstrip("\n"),
                pod=_pod_from_log_stream(by.get("@logStream", "")),
            )
        )
    return WholeTaskSearchResult(
        lines=lines, truncated=len(results_raw) >= _WHOLE_TASK_LIMIT
    )


async def search_whole_devinstance_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    k8s_workspace_name: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
) -> WholeTaskSearchResult:
    """开发机整任务 (跨所有 pod 代次) 搜索, 走 Logs Insights。

    与 search_whole_dynamo_logs 同构, 仅圈定方式不同 (workspace-{CR名} stream 前缀 +
    双容器 workspace/direct-ssh-init, 见 build_devinstance_whole_search_query)。
    """
    import time as _time

    log_group = build_log_group(cluster_tag, cluster_arn)
    now_ms = int(_time.time() * 1000)
    end = end_ms if end_ms is not None else now_ms
    start = start_ms if start_ms is not None else end - _WHOLE_TASK_DEFAULT_WINDOW_MS

    q = build_devinstance_whole_search_query(
        k8s_workspace_name=k8s_workspace_name,
        query=query,
        is_regex=is_regex,
        limit=_WHOLE_TASK_LIMIT,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start,
            end_ms=end,
            query=q,
            limit=_WHOLE_TASK_LIMIT,
            max_seconds=30,
            poll_interval=1.0,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[WholeTaskLogLine] = []
    for ev in results_raw:
        by = {f["field"]: f["value"] for f in ev}
        stream = by.get("stream", "stdout")
        if stream not in ("stdout", "stderr"):
            stream = "stdout"
        lines.append(
            WholeTaskLogLine(
                time=str(by.get("@timestamp", "")),
                stream=stream,
                log=str(by.get("log", "")).rstrip("\n"),
                pod=_pod_from_log_stream(by.get("@logStream", "")),
            )
        )
    return WholeTaskSearchResult(
        lines=lines, truncated=len(results_raw) >= _WHOLE_TASK_LIMIT
    )


async def search_whole_ray_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    ray_cluster_name: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
) -> WholeTaskSearchResult:
    """Ray 整任务 (跨 head + 所有 worker pod) 搜索，走 Logs Insights。

    与 search_whole_dynamo_logs 同构，仅圈定用 rayClusterName 前缀 + 双主容器过滤。
    """
    import time as _time

    log_group = build_log_group(cluster_tag, cluster_arn)
    now_ms = int(_time.time() * 1000)
    end = end_ms if end_ms is not None else now_ms
    start = start_ms if start_ms is not None else end - _WHOLE_TASK_DEFAULT_WINDOW_MS

    q = build_ray_whole_search_query(
        ray_cluster_name=ray_cluster_name,
        query=query,
        is_regex=is_regex,
        limit=_WHOLE_TASK_LIMIT,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start,
            end_ms=end,
            query=q,
            limit=_WHOLE_TASK_LIMIT,
            max_seconds=30,
            poll_interval=1.0,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[WholeTaskLogLine] = []
    for ev in results_raw:
        by = {f["field"]: f["value"] for f in ev}
        stream = by.get("stream", "stdout")
        if stream not in ("stdout", "stderr"):
            stream = "stdout"
        lines.append(
            WholeTaskLogLine(
                time=str(by.get("@timestamp", "")),
                stream=stream,
                log=str(by.get("log", "")).rstrip("\n"),
                pod=_pod_from_log_stream(by.get("@logStream", "")),
            )
        )
    return WholeTaskSearchResult(
        lines=lines, truncated=len(results_raw) >= _WHOLE_TASK_LIMIT
    )


async def search_whole_llmd_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    k8s_name: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
) -> WholeTaskSearchResult:
    """llm-d 整任务 (跨 LWS worker + gateway 所有 pod) 搜索, 走 Logs Insights。

    与 search_whole_dynamo_logs 同构, 仅圈定方式不同 (CR base 名 stream 前缀 +
    双容器 sglang/gateway 过滤, 见 build_llmd_whole_search_query)。
    """
    import time as _time

    log_group = build_log_group(cluster_tag, cluster_arn)
    now_ms = int(_time.time() * 1000)
    end = end_ms if end_ms is not None else now_ms
    start = start_ms if start_ms is not None else end - _WHOLE_TASK_DEFAULT_WINDOW_MS

    q = build_llmd_whole_search_query(
        k8s_name=k8s_name,
        query=query,
        is_regex=is_regex,
        limit=_WHOLE_TASK_LIMIT,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start,
            end_ms=end,
            query=q,
            limit=_WHOLE_TASK_LIMIT,
            max_seconds=30,
            poll_interval=1.0,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[WholeTaskLogLine] = []
    for ev in results_raw:
        by = {f["field"]: f["value"] for f in ev}
        stream = by.get("stream", "stdout")
        if stream not in ("stdout", "stderr"):
            stream = "stdout"
        lines.append(
            WholeTaskLogLine(
                time=str(by.get("@timestamp", "")),
                stream=stream,
                log=str(by.get("log", "")).rstrip("\n"),
                pod=_pod_from_log_stream(by.get("@logStream", "")),
            )
        )
    return WholeTaskSearchResult(
        lines=lines, truncated=len(results_raw) >= _WHOLE_TASK_LIMIT
    )


def _pod_from_log_stream(log_stream: str) -> str:
    """从 @logStream 名提取 pod 名。

    格式: FluentBit/kube.var.log.containers.{pod}_{ns}_{container}-{cid}.log
    取 ``containers.`` 之后到第一个 ``_`` 之间 = 完整 pod 名。取不到返回原串/空。
    """
    marker = "containers."
    idx = log_stream.find(marker)
    if idx < 0:
        return log_stream
    rest = log_stream[idx + len(marker):]
    return rest.split("_", 1)[0]


async def fetch_training_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    training_job_id: str,
    container: str | None = None,
    limit: int = 500,
    since_ms: int | None = None,
) -> tuple[list[LogLine], bool]:
    """Run an Insights query scoped to one TrainingJob.

    Returns:
        (lines, warming_up).
        - ``since_ms=None`` = last 1 hour window
        - ``warming_up=True`` means query completed but returned 0 lines
          (pod just started, Fluent Bit buffer not flushed yet).
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    end_ms = int(time.time() * 1000)
    start_ms = (
        since_ms if since_ms is not None else end_ms - 60 * 60 * 1000
    )
    query = build_training_job_query(
        training_job_id=training_job_id,
        container=container,
        limit=limit,
    )

    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start_ms,
            end_ms=end_ms,
            query=query,
            limit=limit,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[LogLine] = []
    for ev in results_raw:
        parsed = parse_insights_event(ev)
        if parsed is not None:
            lines.append(parsed)

    warming_up = len(lines) == 0
    return lines, warming_up


async def fetch_inference_logs(
    *,
    cluster_tag: str,
    cluster_arn: str,
    inference_id: str,
    container: str | None = None,
    limit: int = 500,
    since_ms: int | None = None,
) -> tuple[list[LogLine], bool]:
    """Insights query scoped to one inference endpoint (复用 training 的 UUID match)."""
    log_group = build_log_group(cluster_tag, cluster_arn)
    end_ms = int(time.time() * 1000)
    start_ms = (
        since_ms if since_ms is not None else end_ms - 60 * 60 * 1000
    )
    # build_training_job_query 名字虽然带 training, 实际只做 UUID 字符串 match,
    # inference id 也是 UUID, 直接复用.
    query = build_training_job_query(
        training_job_id=inference_id,
        container=container,
        limit=limit,
    )
    try:
        results_raw = await run_insights_query(
            log_group=log_group,
            start_ms=start_ms,
            end_ms=end_ms,
            query=query,
            limit=limit,
        )
    except LogGroupNotFoundError as exc:
        raise LogsServiceError(str(exc)) from exc

    lines: list[LogLine] = []
    for ev in results_raw:
        parsed = parse_insights_event(ev)
        if parsed is not None:
            lines.append(parsed)

    warming_up = len(lines) == 0
    return lines, warming_up
