# app/modules/logs/orchestration/history.py
"""训练历史日志业务流 (纯 CloudWatch, 不依赖 K8s).

"""

from __future__ import annotations

from app.adapters.aws import cloudwatch_logs as cw
from app.core.logging import get_logger
from app.modules.logs.api.schemas import (
    HistoryLogLine,
    HistoryLogPage,
    HistoryStreamInfo,
)
from app.modules.logs.domain.filter_pattern import build_log_filter_pattern
from app.modules.logs.domain.history_event import parse_log_event
from app.modules.logs.domain.log_group_naming import build_log_group
from app.modules.logs.domain.stream_naming import (
    assign_seq,
    devinstance_stream_prefix,
    dynamo_stream_prefix,
    inference_stream_prefix,
    llmd_stream_prefix,
    parse_devinstance_stream_name,
    parse_dynamo_stream_name,
    parse_inference_stream_name,
    parse_llmd_stream_name,
    parse_ray_stream_name,
    parse_stream_name,
    ray_stream_prefix,
    trainer_stream_prefix,
)
from app.modules.shared.kueue_status import is_terminal
from app.repositories import resource_index as ri_repo

logger = get_logger(__name__)

# 浏览态每页 100 条 (首屏 + 翻页一致), 方便分页加载测试。
# 浏览态默认页大小 (调用方不显式传 limit 时的兜底):
#   首屏 500 / 翻页 500 (= 前端页面展示量, 人眼查看; 500 通常单次 GetLogEvents 即够,
#   不触发累积翻页)。coding agent (如 Claude Code) 直接调 REST 时可显式传 limit
#   (≤10000) 一次性拉大量, 后端会跨页累积直到攒够。
_FIRST_PAGE_LIMIT = 500
_PAGE_LIMIT = 500
# 端点 limit 参数上限 (面向 agent 大批量; 实际受 _ACCUM_MAX_PAGES × 单页量 约束)
HISTORY_LIMIT_MAX = 10000
# 累积翻页安全上限: 单次请求最多翻这么多页 GetLogEvents。
#   CloudWatch 单页返回 ≤1MB (行长时远不到 limit 条就触顶), 故大 limit 需跨页累积。
#   撞上限即返回已攒的 + 当前 token (调用方可带 token 续翻)。
_ACCUM_MAX_PAGES = 10


async def list_streams(
    *, k8s_job_name: str, cluster_tag: str, cluster_arn: str
) -> list[HistoryStreamInfo]:
    """列该 task 的 trainer stream (= 前端 tab), 按 last_ts 倒序 (最新运行排前)."""
    log_group = build_log_group(cluster_tag, cluster_arn)
    prefix = trainer_stream_prefix(k8s_job_name)
    raw = await cw.describe_log_streams_by_prefix(log_group=log_group, prefix=prefix)

    rows: list[dict] = []
    for s in raw:
        name = s.get("logStreamName", "")
        parsed = parse_stream_name(name)
        if parsed is None:  # 非 trainer (pod-manager / code-sync) 跳过
            continue
        rows.append(
            {
                "stream_name": name,
                "pod_name": parsed["pod_name"],
                "pod_short": parsed["pod_short"],
                "first_ts": int(s.get("firstEventTimestamp") or 0),
                "last_ts": int(s.get("lastEventTimestamp") or 0),
            }
        )
    assign_seq(rows)  # 原地补 seq
    rows.sort(key=lambda r: r["last_ts"], reverse=True)  # 最新运行排前
    return [HistoryStreamInfo(**r) for r in rows]


async def list_inference_streams(
    *, k8s_endpoint_name: str, cluster_tag: str, cluster_arn: str
) -> list[HistoryStreamInfo]:
    """列推理 endpoint 主容器 stream (= 前端 tab), 按 last_ts 倒序 (最新 pod 排前)。

    只含主容器 (= endpoint name); otel-collector / sidecar-reverse-proxy 已在
    parse_inference_stream_name 内过滤掉。多 pod → 多 tab。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    prefix = inference_stream_prefix(k8s_endpoint_name)
    raw = await cw.describe_log_streams_by_prefix(log_group=log_group, prefix=prefix)

    rows: list[dict] = []
    for s in raw:
        name = s.get("logStreamName", "")
        parsed = parse_inference_stream_name(name, k8s_endpoint_name)
        if parsed is None:  # 非主容器 (otel / sidecar) 跳过
            continue
        rows.append(
            {
                "stream_name": name,
                "pod_name": parsed["pod_name"],
                "pod_short": parsed["pod_short"],
                "first_ts": int(s.get("firstEventTimestamp") or 0),
                "last_ts": int(s.get("lastEventTimestamp") or 0),
            }
        )
    assign_seq(rows)
    rows.sort(key=lambda r: r["last_ts"], reverse=True)
    return [HistoryStreamInfo(**r) for r in rows]


async def list_dynamo_streams(
    *, k8s_cr_name: str, cluster_tag: str, cluster_arn: str
) -> list[HistoryStreamInfo]:
    """列 Dynamo (多机推理) 主容器 stream (= 前端 tab), 按 last_ts 倒序。

    前缀圈定 = CR 名 (frontend + 所有 worker pod 都以 {cr_name}- 开头);
    只含主容器 "main", otel-collector sidecar 已在 parse_dynamo_stream_name 内
    过滤掉。多 pod (frontend/worker-ldr/worker-wkr) → 多 tab。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    prefix = dynamo_stream_prefix(k8s_cr_name)
    raw = await cw.describe_log_streams_by_prefix(log_group=log_group, prefix=prefix)

    rows: list[dict] = []
    for s in raw:
        name = s.get("logStreamName", "")
        parsed = parse_dynamo_stream_name(name)
        if parsed is None:  # 非主容器 (otel-collector) 跳过
            continue
        rows.append(
            {
                "stream_name": name,
                "pod_name": parsed["pod_name"],
                "pod_short": parsed["pod_short"],
                "first_ts": int(s.get("firstEventTimestamp") or 0),
                "last_ts": int(s.get("lastEventTimestamp") or 0),
            }
        )
    assign_seq(rows)
    rows.sort(key=lambda r: r["last_ts"], reverse=True)
    return [HistoryStreamInfo(**r) for r in rows]


async def list_devinstance_streams(
    *, k8s_workspace_name: str, cluster_tag: str, cluster_arn: str
) -> list[HistoryStreamInfo]:
    """列开发机 stream (= 前端 tab), 按 last_ts 倒序。

    前缀圈定 = workspace-{CR名} (所有 pod 代次都以此开头);保留主容器 workspace +
    init 容器 direct-ssh-init, 其余 (ssm-agent-sidecar / workspace-init-container) 已在
    parse_devinstance_stream_name 内过滤掉。

    编号: 同一 pod 内 workspace 与 direct-ssh-init 各自独立编号 (按 (pod_short, 容器)
    分组), 不用通用 assign_seq 的纯 pod_short 分组 (照 list_ray_streams)。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    prefix = devinstance_stream_prefix(k8s_workspace_name)
    raw = await cw.describe_log_streams_by_prefix(log_group=log_group, prefix=prefix)

    rows: list[dict] = []
    for s in raw:
        name = s.get("logStreamName", "")
        parsed = parse_devinstance_stream_name(name)
        if parsed is None:  # 非展示容器 (sidecar / init) 跳过
            continue
        rows.append(
            {
                "stream_name": name,
                "pod_name": parsed["pod_name"],
                "pod_short": parsed["pod_short"],
                "first_ts": int(s.get("firstEventTimestamp") or 0),
                "last_ts": int(s.get("lastEventTimestamp") or 0),
                "_container": parsed["container"],
            }
        )
    # 独立编号: 同一 pod 内 workspace 与 direct-ssh-init 各自从 #1 起
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_key.setdefault((r["pod_short"], r["_container"]), []).append(r)
    for group in by_key.values():
        group.sort(key=lambda r: r["first_ts"])
        for i, r in enumerate(group, start=1):
            r["seq"] = i
    for r in rows:
        r.pop("_container", None)
    rows.sort(key=lambda r: r["last_ts"], reverse=True)
    return [HistoryStreamInfo(**r) for r in rows]


async def list_ray_streams(
    *, ray_cluster_name: str, cluster_tag: str, cluster_arn: str
) -> list[HistoryStreamInfo]:
    """列 Ray (rayjob) 主容器 stream (= 前端 tab)，按 last_ts 倒序。

    前缀圈定 = rayClusterName (head + 所有 worker pod 都以 {rayClusterName}- 开头)；
    只含主容器 ray-head/ray-worker，wait-gcs-ready init 容器已在 parse 内过滤。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    prefix = ray_stream_prefix(ray_cluster_name)
    raw = await cw.describe_log_streams_by_prefix(log_group=log_group, prefix=prefix)

    rows: list[dict] = []
    for s in raw:
        name = s.get("logStreamName", "")
        parsed = parse_ray_stream_name(name)
        if parsed is None:  # 非主容器 (wait-gcs-ready) 跳过
            continue
        rows.append(
            {
                "stream_name": name,
                "pod_name": parsed["pod_name"],
                "pod_short": parsed["pod_short"],
                "first_ts": int(s.get("firstEventTimestamp") or 0),
                "last_ts": int(s.get("lastEventTimestamp") or 0),
                "_container": parsed["container"],
            }
        )
    # Ray 专属编号: 同一 pod 内 driver-log-tailer sidecar 与常规容器 (ray-head)
    # 各自独立编号 (不用通用 assign_seq 的纯 pod_short 分组, 否则 driver 与常规会
    # 混进同一个序列)。worker 每 pod 独立 pod_short, 行为与原来一致。
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_key.setdefault((r["pod_short"], r["_container"]), []).append(r)
    for group in by_key.values():
        group.sort(key=lambda r: r["first_ts"])
        for i, r in enumerate(group, start=1):
            r["seq"] = i
    for r in rows:
        r.pop("_container", None)
    rows.sort(key=lambda r: r["last_ts"], reverse=True)
    return [HistoryStreamInfo(**r) for r in rows]


async def list_llmd_streams(
    *, k8s_name: str, cluster_tag: str, cluster_arn: str
) -> list[HistoryStreamInfo]:
    """列 llm-d 主容器 stream (= 前端 tab), 按 last_ts 倒序。

    前缀圈定 = CR base 名 (LWS worker + gateway pod 都以 {k8s_name}- 开头);
    只含主容器 sglang/gateway, worker-otel-collector sidecar 已在 parse_llmd_stream_name
    内过滤掉。多 pod (leader/worker/gateway 各副本) → 多 tab。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    prefix = llmd_stream_prefix(k8s_name)
    raw = await cw.describe_log_streams_by_prefix(log_group=log_group, prefix=prefix)

    rows: list[dict] = []
    for s in raw:
        name = s.get("logStreamName", "")
        parsed = parse_llmd_stream_name(name)
        if parsed is None:  # 非主容器 (worker-otel-collector / kube-api-access) 跳过
            continue
        rows.append(
            {
                "stream_name": name,
                "pod_name": parsed["pod_name"],
                "pod_short": parsed["pod_short"],
                "first_ts": int(s.get("firstEventTimestamp") or 0),
                "last_ts": int(s.get("lastEventTimestamp") or 0),
            }
        )
    assign_seq(rows)
    rows.sort(key=lambda r: r["last_ts"], reverse=True)
    return [HistoryStreamInfo(**r) for r in rows]


# stream 列表回填 DDB 的条数上限。单 DDB item 硬上限 400KB, 留足余量后
# 取 400 条 (每条 stream 元数据 ~百字节级), 超限则只返回不写缓存, 避免撑爆 item。
MAX_CACHED_STREAMS = 400


async def get_or_cache_streams(
    *,
    cached_log_streams: list[dict] | None,
    kueue_status: str | None,
    workspace_id: str,
    resource_id: str,
    resource_type: str,
    list_fn,
    list_fn_kwargs: dict,
) -> list[HistoryStreamInfo]:
    """懒加载缓存编排: stream 列表只在任务终态时回填一次 DDB, 之后零 CloudWatch 命中。

    - 命中缓存 (cached_log_streams 非空): 直接反序列化返回, 不碰 CloudWatch。
    - 未命中: 调 list_fn (纯 CloudWatch) 拉实时列表。
    - 仅当 is_terminal(kueue_status) 且条数 <= MAX_CACHED_STREAMS 时回填 DDB
      (终态后列表不再变, 才值得缓存; Evicted 是中间态不触发)。回填失败 / 非终态 /
      超上限 都不阻塞返回。
    """
    if cached_log_streams:
        return [HistoryStreamInfo(**r) for r in cached_log_streams]

    streams = await list_fn(**list_fn_kwargs)

    if is_terminal(kueue_status) and len(streams) <= MAX_CACHED_STREAMS:
        try:
            await ri_repo.update_business_fields(
                workspace_id=workspace_id,
                resource_type=resource_type,
                resource_id=resource_id,
                fields={"log_streams": [s.model_dump() for s in streams]},
            )
        except Exception as exc:  # noqa: BLE001 — 缓存回填失败不应阻塞读路径
            logger.warning("log_streams.cache_write_fail", rid=resource_id, err=str(exc))
    elif is_terminal(kueue_status):
        logger.warning(
            "log_streams.cache_skip_over_cap", rid=resource_id, count=len(streams)
        )

    return streams


# 首次空响应自动跟随 backward token 的最大跳数 (防空 stream 死循环)。
_EMPTY_FOLLOW_MAX = 5


def _to_lines(events: list) -> list[HistoryLogLine]:
    return [HistoryLogLine(**parse_log_event(ev.get("message", ""))) for ev in events]


async def fetch_page(
    *,
    cluster_tag: str,
    cluster_arn: str,
    stream: str,
    token: str | None,
    load_dir: str | None = None,
    anchor: str = "newest",
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int | None = None,
) -> HistoryLogPage:
    """浏览态单 stream 翻页 (GetLogEvents, 同屏双向, 窗口内恒旧→新)。

    首屏 (token=None) 由 anchor 决定定位端 (两种都返回双向 token, 之后都能两头翻):
        - "newest" (默认, 新→旧): startFromHead=False 定位最新, 打开滚到底。
        - "oldest" (旧→新):       startFromHead=True  定位最早, 打开停顶
                                   (看环境变量/启动配置等开头日志, 无需上滑翻很久)。
    翻页 (带 token) 由 load_dir 决定:
        - "forward" : 往更新翻 (下滑; 运行中任务拉新日志)。返回新 forward_token。
        - "backward": 往更早翻 (上滑)。返回新 backward_token。
    start_ms/end_ms 可选时间窗 (GetLogEvents 原生支持且保留双向 token)。
    limit 每页条数: None → 按场景兜底 (首屏 _FIRST_PAGE_LIMIT / 翻页 _PAGE_LIMIT);
        显式传 → 首屏/翻页都用该值 (coding agent 一次性拉大量时传, ≤HISTORY_LIMIT_MAX)。

    ⚠️ GetLogEvents 单页 ≤1MB (行长时远不到 limit 条就触顶), 故攒够 target 需跨页累积
    (最多 _ACCUM_MAX_PAGES 页)。空响应跟随同向指针 (旧 empty-follow 逻辑已融入累积)。
    events 恒时间升序。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)

    # 方向: 翻页由 load_dir 定; 首屏由 anchor 定 (newest→往旧翻/from_head=False,
    #       oldest→往新翻/from_head=True)。
    if token is not None:
        target = limit if limit is not None else _PAGE_LIMIT
        from_head = load_dir == "forward"
    else:
        target = limit if limit is not None else _FIRST_PAGE_LIMIT
        from_head = anchor == "oldest"

    # forward (from_head=True): 往更新累积, 每批 append, 收尾取 forward_token。
    # backward (from_head=False): 往更旧累积, 每批 prepend, 收尾取 backward_token。
    follow_key = "next_forward_token" if from_head else "next_backward_token"
    lines: list[HistoryLogLine] = []
    cur_token: str | None = token
    first_forward: str | None = None   # 首批(最新端)的 forward token
    first_backward: str | None = None  # 首批的 backward token
    last_forward: str | None = None
    last_backward: str | None = None

    for _ in range(_ACCUM_MAX_PAGES):
        resp = await cw.get_log_events(
            log_group=log_group, stream=stream, start_from_head=from_head,
            next_token=cur_token, limit=target,
            start_ms=start_ms, end_ms=end_ms,
        )
        fwd = resp.get("next_forward_token")
        bwd = resp.get("next_backward_token")
        if first_forward is None:  # 记首批两端 token
            first_forward, first_backward = fwd, bwd
        last_forward, last_backward = fwd, bwd

        batch = _to_lines(resp["events"])
        if batch:
            if from_head:
                lines.extend(batch)          # 往新: 追加在后
            else:
                lines[:0] = batch            # 往旧: 插在前 (保持 old→new)

        follow = resp.get(follow_key)
        # 到头 (指针不再前进) 或已攒够 → 停
        if follow is None or follow == cur_token or len(lines) >= target:
            break
        cur_token = follow

    # token 语义 (窗口内 old→new, 两端各给一个方向 token 供前端续翻):
    #   forward_token = 最新端 (往更新翻); backward_token = 最旧端 (往更早翻)。
    # 往旧累积时: 最新端=首批, 最旧端=末批; 往新累积时反之。
    if from_head:
        fwd_out, bwd_out = last_forward, first_backward
    else:
        fwd_out, bwd_out = first_forward, last_backward

    # 翻页 (带 token) 只返回该方向的续翻 token, 与旧行为一致 (前端 loadUp/loadDown
    # 分别只读对应一侧 token)。
    if token is not None:
        if load_dir == "forward":
            return HistoryLogPage(lines=lines, forward_token=fwd_out, mode="browse")
        return HistoryLogPage(lines=lines, backward_token=bwd_out, mode="browse")
    return HistoryLogPage(
        lines=lines, forward_token=fwd_out, backward_token=bwd_out, mode="browse")


# ===== 搜索 / 时间过滤翻页 (FilterLogEvents, direction 定方向) =====
# 每页 100 条 (方便分页加载测试)。API limit 与 target 一致, 单页即返回。
_FILTER_API_LIMIT = 100
# 后端单次请求内攒够这么多行即返回给前端 (= 前端一批展示量)。
_FILTER_TARGET_LINES = 100
# 单次请求最多翻这么多页 (防大时间窗 + 稀疏命中时一个请求扫太久)。
_FILTER_MAX_PAGES = 10


async def search_page(
    *,
    cluster_tag: str,
    cluster_arn: str,
    stream: str,
    query: str,
    is_regex: bool,
    start_ms: int | None,
    end_ms: int | None,
    token: str | None,
) -> HistoryLogPage:
    """按 filterPattern + 时间窗在单 stream 内搜索一页 (恒旧→新)。

    走 FilterLogEvents: 结果时间升序, 单个 next_token 只能往更新翻 (只支持旧→新,
    原因见 adapter.filter_log_events 注释)。后端在一次请求内翻页累积, 直到攒够
    _FILTER_TARGET_LINES 行、翻满 _FILTER_MAX_PAGES 页、或 next_token 耗尽为止,
    返回累积行 + 末尾 next_token。

    next_token 为 None 表示已到最新 (无更多); 前端下滑续传 token 继续。
    query 为空串时 filter_pattern 为空 = 仅按时间窗过滤。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    filter_pattern = build_log_filter_pattern(query=query, is_regex=is_regex)

    lines: list[HistoryLogLine] = []
    cur_token = token
    for _ in range(_FILTER_MAX_PAGES):
        resp = await cw.filter_log_events(
            log_group=log_group,
            stream=stream,
            filter_pattern=filter_pattern,
            start_ms=start_ms,
            end_ms=end_ms,
            next_token=cur_token,
            limit=_FILTER_API_LIMIT,
        )
        for ev in resp["events"]:
            lines.append(HistoryLogLine(**parse_log_event(ev.get("message", ""))))
        cur_token = resp.get("next_token")
        if cur_token is None or len(lines) >= _FILTER_TARGET_LINES:
            break
    return HistoryLogPage(lines=lines, next_token=cur_token, mode="search")


async def iter_all_lines(
    *, cluster_tag: str, cluster_arn: str, stream: str
):
    """下载用: 从头翻到底, 逐行 yield 格式化文本 (流式, 不全攒内存).

    CloudWatch get_log_events 到头时返回相同 forward token + 空 events → 停止。
    """
    log_group = build_log_group(cluster_tag, cluster_arn)
    token: str | None = None
    while True:
        resp = await cw.get_log_events(
            log_group=log_group,
            stream=stream,
            start_from_head=True,  # 下载从头正序
            next_token=token,
            limit=_PAGE_LIMIT,
        )
        events = resp["events"]
        if not events:
            break
        for ev in events:
            line = parse_log_event(ev.get("message", ""))
            yield f"{line['time']} [{line['stream']}] {line['log']}\n"
        new_token = resp.get("next_forward_token")
        if new_token == token:  # 到头, token 不再前进
            break
        token = new_token
