"""Log tail routes for training jobs (DDB-only).

提供 2 个端点:
- GET /training-jobs/{id}/logs        历史 (CloudWatch Insights, 带 since_ms 光标)
- GET /training-jobs/{id}/logs/stream 实时 SSE (kubectl logs --follow, Pod 活才用)
"""

from __future__ import annotations

import json
import time
from typing import AsyncIterator

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.adapters.aws.cloudwatch_logs import (
    InvalidPageTokenError,
    LogGroupNotFoundError,
)
from app.adapters.ddb import tables
from app.adapters.k8s import K8sClient
from app.core.config import get_settings
from app.core.i18n import t
from app.core.logging import get_logger
from app.core.security import (
    assert_ws_member,
    get_current_user,
    get_current_user_allow_query,
)
from app.modules.cluster import crud as cluster_crud
from app.modules.logs.api.schemas import (
    HistoryLogPage,
    HistoryStreamInfo,
    LogResponse,
    WholeTaskSearchResult,
)
from app.modules.logs.domain.filter_pattern import FilterPatternError
from app.modules.logs.domain.insights_query import InsightsQueryError
from app.modules.logs.domain.log_group_naming import split_log_group
from app.modules.logs.domain.stream_naming import (
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
from app.modules.logs.orchestration import (
    LogsServiceError,
    fetch_inference_logs,
    fetch_training_logs,
    search_whole_devinstance_logs,
    search_whole_dynamo_logs,
    search_whole_inference_logs,
    search_whole_llmd_logs,
    search_whole_ray_logs,
    search_whole_task_logs,
)
from app.modules.logs.orchestration import history
from app.modules.devinstance.persistence import crud as dev_crud
from app.modules.dynamo.persistence import crud as dyn_crud
from app.modules.rayjob.persistence import crud as ray_crud
from app.modules.llmd.persistence import crud as llmd_crud
from app.modules.inference.persistence import crud as inf_crud
from app.modules.training import crud as train_crud
from app.modules.workspace import crud as ws_crud

logger = get_logger(__name__)

logs_router = APIRouter(tags=["logs"])


def _sse_event(data: dict) -> str:
    """SSE 单条 event 格式: data: <json>\\n\\n"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@logs_router.get(
    "/training-jobs/{id}/logs",
    response_model=LogResponse,
    summary="拉取训练任务的 CloudWatch 历史日志",
    description=(
        "读取训练任务的 CloudWatch 日志 (轮询式追尾):\n\n"
        "- **数据源**: CloudWatch **Logs Insights** (`fetch_training_logs` → `start_query` + 轮询 `get_query_results`), "
        "按 `@message like \"<job_id>\"` 圈定该任务\n"
        "- `since_ms`: unix 毫秒下界 (**含**, 即 Insights 查询的 startTime). 响应里的 `next_since_ms` = 末行时间 + 1ms, "
        "下次带上即可无重复轮询式 tail; 不传 = 默认查最近 1 小时\n"
        "- `container`: 可选, HyperPodPyTorchJob 传 `trainer` 只取主训练容器日志\n"
        "- `limit`: 1-2000, 默认 500\n"
        "- `warming_up=true`: 查询成功但 0 行 (Pod 刚起, Fluent Bit 还没 flush)\n\n"
        "仅只读, 仅该 job 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
        502: {"description": "workspace / cluster 未挂 CloudWatch (集群 arn 缺失), 或 CloudWatch log group 不存在"},
    },
)
async def training_job_logs(
    id: str,  # noqa: A002
    container: str | None = Query(
        default=None,
        description='Filter by container name (e.g. "trainer" for HPJ pods)',
    ),
    limit: int = Query(default=500, ge=1, le=2000),
    since_ms: int | None = Query(
        default=None,
        description=(
            "Unix millis lower bound (inclusive). Pass `next_since_ms` from a "
            "prior response (= last line ts + 1ms) to tail without duplicates. "
            "Omit to query the last 1 hour."
        ),
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> LogResponse:
    job = await train_crud.get(None, id)
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    # 仅该 job 所属 ws 的成员或超管可读日志 (越权修复 2026-06-14)
    await assert_ws_member(str(job.get("workspace_id")), current_user)
    ws = await ws_crud.get_workspace(None, job.get("workspace_id"))
    if ws is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "workspace missing for training job",
        )
    cluster = await cluster_crud.get_cluster_by_id(None, ws.get("cluster_id"))
    if cluster is None or not cluster.get("hyperpod_cluster_arn"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "cluster has no hyperpod_cluster_arn; logs unavailable",
        )

    try:
        lines, warming_up = await fetch_training_logs(
            cluster_tag=cluster.get("cluster_tag") or "",
            cluster_arn=cluster.get("hyperpod_cluster_arn") or "",
            training_job_id=str(job.get("id") or job.get("resource_id") or ""),
            container=container,
            limit=limit,
            since_ms=since_ms,
        )
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    next_since = (lines[-1].timestamp_ms + 1) if lines else since_ms
    return LogResponse(
        lines=lines,
        next_since_ms=next_since,
        warming_up=warming_up,
        source="cloudwatch",
    )


@logs_router.get(
    "/training-jobs/{id}/logs/stream",
    summary="实时 SSE 推送训练 Pod 的 stdout 日志",
    description=(
        "**SSE 流式** (`text/event-stream`) 推送单个训练 Pod 的实时 stdout 日志:\n\n"
        "- **数据源**: K8s `kubectl logs --follow` (Pod 存活时). Pod 死后请转用 `/logs` 走 CloudWatch\n"
        "- 事件类型: `open` (连上) / `log` (每行 stdout) / `error` (读日志异常) / `close` (收尾)\n"
        "- `pod`: 必传, 从 `/training-jobs/{id}` 详情里的 pod 列表拿\n"
        "- `container`: 多容器 Pod 必传, HyperPodPyTorchJob 固定 `trainer`\n"
        "- `tail_lines`: 首次连接时倒推的行数 (0-10000, 默认 200)\n"
        "- **鉴权走 query token** (`get_current_user_allow_query`), 前端 EventSource 无法自定义 Header\n"
        "- 断开: 前端关 EventSource → 服务端 cancel async generator → 释放 K8s watch 连接\n"
        "- **Pod 不存在 / 未运行不报 HTTP 错**: 响应已是 200 流, 只推一条 `error` 事件再 `close` "
        "(此时转用 `/logs` 走 CloudWatch 归档)\n\n"
        "仅只读, 仅该 job 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
    },
)
async def training_job_logs_stream(
    id: str,  # noqa: A002
    pod: str = Query(..., description="Pod name (从 /training-jobs/{id} 详情拿)"),
    container: str = Query(
        default="trainer",
        description="多容器 Pod 必传, HyperPodPyTorchJob = 'trainer'",
    ),
    tail_lines: int = Query(default=200, ge=0, le=10000),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    """SSE 推 Pod stdout 实时日志.

    数据源: kubectl logs --follow (Pod 活时). Pod 死走 /logs (CloudWatch).
    断开: 浏览器关 EventSource → server cancel async generator → 释放 K8s 连接.
    """
    job = await train_crud.get(None, id)
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    # 仅该 job 所属 ws 的成员或超管可看实时日志 (越权修复 2026-06-14)
    await assert_ws_member(str(job.get("workspace_id")), current_user)
    namespace = job.get("k8s_namespace") or "default"

    async def _gen() -> AsyncIterator[bytes]:
        # 1. 通知客户端 stream 起始 (前端可标"实时连上")
        yield _sse_event({"type": "open", "pod": pod, "ts": int(time.time() * 1000)}).encode()

        k8s = K8sClient()
        try:
            async for line in k8s.stream_pod_logs(
                namespace=namespace,
                pod_name=pod,
                container=container,
                tail_lines=tail_lines,
            ):
                payload = {
                    "type": "log",
                    "ts": int(time.time() * 1000),
                    "line": line,
                    "pod": pod,
                }
                yield _sse_event(payload).encode()
        except Exception as exc:  # noqa: BLE001
            logger.info("logs.stream.fail", id=id, pod=pod, err=str(exc))
            yield _sse_event({"type": "error", "msg": str(exc)}).encode()
        finally:
            yield _sse_event({"type": "close"}).encode()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁 nginx / 反向代理 buffering
            "Connection": "keep-alive",
        },
    )


# ============================================================
# Inference endpoint logs (复用 training 的 CW Insights / SSE 实现)
# ============================================================


@logs_router.get(
    "/inferences/{id}/logs",
    response_model=LogResponse,
    summary="拉取推理服务的 CloudWatch 历史日志",
    description=(
        "读取推理服务的 CloudWatch 日志 (与训练同构, 轮询式追尾):\n\n"
        "- **数据源**: CloudWatch **Logs Insights** (`fetch_inference_logs`, 复用训练的 `@message like \"<id>\"` "
        "UUID 匹配 → `start_query` + 轮询)\n"
        "- `since_ms`: unix 毫秒下界 (**含**). 传上一次 `next_since_ms` (末行时间 + 1ms) 无重复 tail; "
        "不传 = 默认查最近 1 小时\n"
        "- `container`: 可选, SGLang Inference Operator 起的 main 容器名 = endpoint name\n"
        "- `limit`: 1-2000, 默认 500\n"
        "- `warming_up=true`: 查询成功但 0 行 (Pod 刚起, 日志未 flush)\n\n"
        "仅只读, 仅该推理所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理服务不存在"},
        502: {"description": "workspace / cluster 未挂 CloudWatch (集群 arn 缺失), 或 CloudWatch log group 不存在"},
    },
)
async def inference_logs(
    id: str,  # noqa: A002
    container: str | None = Query(
        default=None,
        description='Filter by container name (e.g. SGLang main container)',
    ),
    limit: int = Query(default=500, ge=1, le=2000),
    since_ms: int | None = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> LogResponse:
    inf = await inf_crud.get(None, id)
    if inf is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    # 仅该 inference 所属 ws 的成员或超管可读日志 (越权修复 2026-06-14)
    await assert_ws_member(str(inf.get("workspace_id")), current_user)
    ws = await ws_crud.get_workspace(None, inf.get("workspace_id"))
    if ws is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "workspace missing for inference"
        )
    cluster = await cluster_crud.get_cluster_by_id(None, ws.get("cluster_id"))
    if cluster is None or not cluster.get("hyperpod_cluster_arn"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "cluster has no hyperpod_cluster_arn; logs unavailable",
        )

    try:
        lines, warming_up = await fetch_inference_logs(
            cluster_tag=cluster.get("cluster_tag") or "",
            cluster_arn=cluster.get("hyperpod_cluster_arn") or "",
            inference_id=str(inf.get("id") or inf.get("resource_id") or ""),
            container=container,
            limit=limit,
            since_ms=since_ms,
        )
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    next_since = (lines[-1].timestamp_ms + 1) if lines else since_ms
    return LogResponse(
        lines=lines,
        next_since_ms=next_since,
        warming_up=warming_up,
        source="cloudwatch",
    )


@logs_router.get(
    "/inferences/{id}/logs/stream",
    summary="实时 SSE 推送推理 Pod 的 stdout 日志",
    description=(
        "**SSE 流式** (`text/event-stream`) 推送单个推理 Pod 的实时 stdout 日志:\n\n"
        "- **数据源**: K8s `kubectl logs --follow` (Pod 存活时). Pod 死后转用 `/logs` 走 CloudWatch\n"
        "- 事件类型: `open` / `log` / `error` / `close`\n"
        "- `pod`: 必传, 从推理详情里的 pod 列表拿\n"
        "- `container`: 缺省 fallback 到 endpoint name (SGLang Inference Operator 起的 main 容器名 = endpoint name)\n"
        "- `tail_lines`: 首次连接时倒推的行数 (0-10000, 默认 200)\n"
        "- **鉴权走 query token** (EventSource 限制)\n"
        "- **Pod 不存在 / 未运行不报 HTTP 错**: 响应已是 200 流, 只推一条 `error` 事件再 `close` "
        "(此时转用 `/logs` 走 CloudWatch 归档)\n\n"
        "仅只读, 仅该推理所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理服务不存在"},
    },
)
async def inference_logs_stream(
    id: str,  # noqa: A002
    pod: str = Query(..., description="Pod name (从详情拿)"),
    container: str | None = Query(
        default=None,
        description="多容器 Pod 必传; SGLang Inference Operator 起的 main 容器名 = endpoint name",
    ),
    tail_lines: int = Query(default=200, ge=0, le=10000),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    inf = await inf_crud.get(None, id)
    if inf is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    # 仅该 inference 所属 ws 的成员或超管可看实时日志 (越权修复 2026-06-14)
    await assert_ws_member(str(inf.get("workspace_id")), current_user)
    namespace = inf.get("k8s_namespace") or "default"
    # SGLang Inference Operator: Deployment 起的 main 容器名 = k8s_endpoint_name.
    final_container = container or (inf.get("k8s_endpoint_name") or "")

    async def _gen() -> AsyncIterator[bytes]:
        yield _sse_event(
            {"type": "open", "pod": pod, "ts": int(time.time() * 1000)}
        ).encode()
        k8s = K8sClient()
        try:
            async for line in k8s.stream_pod_logs(
                namespace=namespace,
                pod_name=pod,
                container=final_container,
                tail_lines=tail_lines,
            ):
                payload = {
                    "type": "log",
                    "ts": int(time.time() * 1000),
                    "line": line,
                    "pod": pod,
                }
                yield _sse_event(payload).encode()
        except Exception as exc:  # noqa: BLE001
            logger.info("logs.inference.stream.fail", id=id, pod=pod, err=str(exc))
            yield _sse_event({"type": "error", "msg": str(exc)}).encode()
        finally:
            yield _sse_event({"type": "close"}).encode()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ============================================================
# 历史日志端点 (完成/报错 task · CloudWatch get_log_events)
# ============================================================


async def _resolve_cluster_log_target(workspace_id: Any) -> tuple[str, str]:
    """产出 (cluster_tag, cluster_arn) 供下游 build_log_group 拼 CloudWatch log group。

    两条路 (语义等价, 只是数据源不同, 均不涉及鉴权):
    - **快路径**: settings.log_group_name 配了完整 log group 名 (单集群部署) →
      反解出 tag + cluster-id-suffix, 直接返回, **跳过 ws_get + SageMaker
      DescribeCluster** (省 ~0.9s + ~1.8s/请求)。cluster_arn 只需结尾 suffix 对,
      build_log_group 内部 rsplit("/") 取的就是它, 故用合成 arn 承载 suffix。
    - **回退**: 未配 (或格式不符) → 按 ws->cluster 动态查 (多集群 / 未配时不破)。

    鉴权已在调用方 assert_ws_member 完成; 本函数只解析 log group 目标, 无授权语义。
    """
    log_group_name = get_settings().log_group_name
    if log_group_name:
        parsed = split_log_group(log_group_name)
        if parsed is not None:
            tag, suffix = parsed
            # 合成 arn: build_log_group 只 rsplit("/") 取末段 suffix, 故仅需结尾对。
            return tag, f"arn:aws:sagemaker:::cluster/{suffix}"
        logger.warning("log_group_name.malformed", value=log_group_name)

    ws = await ws_crud.get_workspace(None, workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "workspace missing for resource")
    cluster = await cluster_crud.get_cluster_by_id(None, ws.get("cluster_id"))
    if cluster is None or not cluster.get("hyperpod_cluster_arn"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "cluster has no hyperpod_cluster_arn; logs unavailable",
        )
    return str(cluster.get("cluster_tag") or ""), str(
        cluster.get("hyperpod_cluster_arn") or ""
    )


async def _resolve_log_ctx(
    id_: str, current_user: dict[str, Any]
) -> dict[str, Any]:
    """training id → dict(k8s_job_name/cluster_tag/cluster_arn + 缓存所需 task 行字段).

    顺带做成员闸门: 非该 job 所属 ws 的成员/超管一律 403 (越权修复 2026-06-14)。
    透出 kueue_status/workspace_id/resource_id/cached_log_streams 给 log-streams
    端点接懒加载缓存 (避免再查一次 task 行)。
    """
    job = await train_crud.get(None, id_)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"training job not found: {id_}")
    await assert_ws_member(str(job.get("workspace_id")), current_user)
    cluster_tag, cluster_arn = await _resolve_cluster_log_target(job.get("workspace_id"))
    return {
        "k8s_job_name": str(job.get("k8s_job_name") or ""),
        "cluster_tag": cluster_tag,
        "cluster_arn": cluster_arn,
        "kueue_status": job.get("kueue_status"),
        "workspace_id": str(job.get("workspace_id") or ""),
        "resource_id": str(job.get("id") or ""),
        "cached_log_streams": job.get("log_streams"),
    }


def _assert_stream_belongs(k8s_job_name: str, stream: str) -> None:
    """stream 必须属于本 task (前缀匹配), 否则 403 防越权读别的 task."""
    if not stream.startswith(trainer_stream_prefix(k8s_job_name)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "stream does not belong to this training job"
        )


@logs_router.get(
    "/training-jobs/{id}/log-streams",
    response_model=list[HistoryStreamInfo],
    summary="列出训练任务的历史 log stream (前端 tab)",
    description=(
        "枚举训练任务在 CloudWatch 里的 trainer 容器 log streams, 每个 stream 对应前端一个"
        "历史日志 tab (多节点 / auto-resume 重启会产生多个 stream):\n\n"
        "- **数据源**: CloudWatch Logs `DescribeLogStreams` (通过 `stream_naming.trainer_stream_prefix` 按 job 前缀过滤)\n"
        "- **懒加载缓存**: task 终态后首次列出会写回 DDB `log_streams` 字段 (仅 ≤400 条时写, 防撑爆 DDB item), "
        "后续直接命中缓存, 避免反复调 DescribeLogStreams (task 还在跑时每次都实时查)\n"
        "- 返回 stream 名 + first/last event 时间, 供前端排序展示 tab\n\n"
        "仅只读, 仅该 job 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
        502: {"description": "CloudWatch log group 不存在 (集群未开日志 / 尚未产日志)"},
    },
)
async def training_log_streams(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[HistoryStreamInfo]:
    ctx = await _resolve_log_ctx(id, current_user)
    try:
        return await history.get_or_cache_streams(
            cached_log_streams=ctx["cached_log_streams"],
            kueue_status=ctx["kueue_status"],
            workspace_id=ctx["workspace_id"],
            resource_id=ctx["resource_id"],
            resource_type=tables.RESOURCE_TYPE_TRAIN,
            list_fn=history.list_streams,
            list_fn_kwargs={
                "k8s_job_name": ctx["k8s_job_name"],
                "cluster_tag": ctx["cluster_tag"],
                "cluster_arn": ctx["cluster_arn"],
            },
        )
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/training-jobs/{id}/logs/history",
    response_model=HistoryLogPage,
    summary="翻页/搜索训练单个 stream 的历史日志",
    description=(
        "单个 stream (= 前端一个 tab) 内的历史日志翻页 / 搜索, 双模式:\n\n"
        "- **无 query** → CloudWatch `GetLogEvents` **浏览态**, 支持双向翻页:\n"
        "  - 首屏 `anchor=newest` 定位最新 (滚到底) 或 `oldest` 定位最早 (看开头)\n"
        "  - `load_dir=forward` 下滑追更新, `backward` 上滑看更早\n"
        "  - 纯时间筛选 (`start_ms/end_ms`, 无 query) 也走这里, 保住双向翻页\n"
        "- **有 query** → CloudWatch `FilterLogEvents` **搜索态**, 恒旧→新单向:\n"
        "  - `is_regex=false` 是关键字子串匹配, `true` 走 CloudWatch filter pattern 正则\n"
        "  - `next_token` 下滑加载更新命中\n\n"
        "浏览与搜索的 `token` 语义不同, 前端切换条件时必须清空 token 再请求.\n"
        "**stream 前缀校验**: 传入的 `stream` 必须以 `trainer_stream_prefix(k8s_job_name)` 开头, 否则 403 防越权读别的 job.\n\n"
        "仅只读, 仅该 job 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "filter pattern 语法错误 (正则/关键字非法)"},
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 job"},
        404: {"description": "训练任务不存在"},
        409: {"description": "翻页 token 与当前查询模式不匹配 / 已过期, 前端需清 token 重查"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def training_logs_history(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    token: str | None = Query(default=None, description="next_token from prior page"),
    query: str = Query(default="", description="搜索词 (空=不按内容过滤)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析 (否则关键字子串)"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒, 可选)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒, 可选)"),
    load_dir: str | None = Query(
        default=None,
        pattern="^(forward|backward)$",
        description="浏览态翻页方向: 空=首屏(定位,返双向token); forward=往更新(下滑); backward=往更早(上滑)。搜索态忽略。",
    ),
    anchor: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="浏览首屏定位端: newest=最新(新→旧,滚到底); oldest=最早(旧→新,停顶,看开头日志)。搜索态忽略。",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=history.HISTORY_LIMIT_MAX,
        description=(
            "浏览态每页条数 (仅无 query 时生效; 搜索态忽略)。"
            "留空 = 按场景默认 500 (首屏 / 翻页同值, 供页面查看)。"
            "coding agent 可显式传大值 (≤10000) 一次性拉大量, 减少翻页; "
            "受单请求最多累积 10 页 + GetLogEvents 单页 ≤1MB 约束, 实际可能少于所要条数。"
        ),
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryLogPage:
    """单 stream 历史日志翻页 / 搜索。

    - 无 query → GetLogEvents 浏览 (同屏双向: 首屏定位最新, forward_token 下滑追更新,
      backward_token 上滑看更早; 纯时间筛选也走这里, 保住双向)。
    - 有 query → FilterLogEvents 搜索 (恒旧→新单向; next_token 下滑加载更新)。
    浏览与搜索的 token 语义不同, 不可混用 (前端切换条件时须清空 token)。
    """
    ctx = await _resolve_log_ctx(id, current_user)
    _assert_stream_belongs(ctx["k8s_job_name"], stream)
    # 仅"有搜索词"才走 FilterLogEvents (锁旧→新); 纯时间筛选走 GetLogEvents 保住双向。
    use_search = bool(query.strip())
    try:
        if use_search:
            # 搜索态恒旧→新 (FilterLogEvents 只支持正序, 见 adapter 注释)
            return await history.search_page(
                cluster_tag=ctx["cluster_tag"],
                cluster_arn=ctx["cluster_arn"],
                stream=stream,
                query=query,
                is_regex=is_regex,
                start_ms=start_ms,
                end_ms=end_ms,
                token=token,
            )
        return await history.fetch_page(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            stream=stream,
            token=token,
            load_dir=load_dir,
            anchor=anchor,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )
    except FilterPatternError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidPageTokenError as exc:
        # token 与当前查询模式不匹配 (浏览↔搜索切换残留) / 已过期 → 让前端清 token 重查
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            t("logs.page_token_invalid"),
        ) from exc
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/training-jobs/{id}/logs/search-all",
    response_model=WholeTaskSearchResult,
    summary="整任务搜索: 跨训练所有 pod 的日志 (Insights)",
    description=(
        "**整任务 (whole-task) 日志搜索**: 一次性跨该训练任务名下所有 pod 的 trainer 容器日志:\n\n"
        "- **数据源**: CloudWatch Logs Insights (`search_whole_task_logs`), **同步执行 + 轮询** (启动 query → 轮询 status → 取 results)\n"
        "- 圈定范围: K8s label 精确匹配 `kubernetes.labels.platform.hyperpod.io/training-job-id = <id>` 圈整任务 "
        "(跨所有 pod / auto-resume 重启) + 只 `trainer` 容器 (排掉 sidecar) + 可选 `query` (限定 `log` 正文)\n"
        "- 时间窗: `start_ms/end_ms` 默认近 24h → now (unix 毫秒)\n"
        "- `is_regex=true` 走 Insights `like /pattern/` 正则 (**不支持斜杠 `/`**, 会 400); `false` 走子串 `like \"...\"` (大小写敏感)\n"
        "- **单次上限 1 万行**, 命中封顶时 `truncated=true` (前端提示缩小时间窗 / 加关键字)\n\n"
        "仅只读, 仅该 job 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "Insights query 参数非法 (时间窗 / 正则语法错误)"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
        502: {"description": "CloudWatch / cluster 未挂日志"},
    },
)
async def training_logs_search_all(

    id: str,  # noqa: A002
    query: str = Query(default="", description="搜索词 (空=整任务全部日志)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒; 默认近24h)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒; 默认 now)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WholeTaskSearchResult:
    """整任务 (跨所有 pod) 日志搜索。走 Logs Insights, 用 job_id 圈定整任务 + 只
    trainer 容器 + 可选关键字/正则 (限定正文)。异步查询, 单次最多返回 1 万行,
    命中达上限 → truncated=True (前端提示缩小时间窗或加关键字)。
    """
    ctx = await _resolve_log_ctx(id, current_user)
    try:
        return await search_whole_task_logs(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            training_job_id=ctx["resource_id"],
            query=query,
            is_regex=is_regex,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InsightsQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/training-jobs/{id}/logs/history/download",
    summary="下载训练单个 stream 的完整历史日志为文本",
    description=(
        "把训练任务单个 stream 的**完整历史日志** (从头到尾, 无翻页) 打成 `text/plain` 文件下载:\n\n"
        "- **数据源**: CloudWatch Logs `GetLogEvents` 循环拉全 (`history.iter_all_lines`), 生成器流式写响应, 避免全量入内存\n"
        "- 文件名带 `pod_short + container_id[:8]`, 区分同任务的多个 stream (多节点 / auto-resume 多 tab)\n"
        "- **stream 前缀校验**: 必须属于本 job\n"
        "- **鉴权走 query token** (下载走浏览器 `<a href>`, 无法自定义 Header)\n\n"
        "仅只读, 仅该 job 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 job"},
        404: {"description": "训练任务不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def training_logs_history_download(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    ctx = await _resolve_log_ctx(id, current_user)
    _assert_stream_belongs(ctx["k8s_job_name"], stream)
    # 文件名带 pod + container_id 区分同 task 的多个 stream (多节点 / auto-resume
    # 重启 → 多 tab), 避免每个 tab 都下成同名文件。
    parsed = parse_stream_name(stream)
    if parsed:
        suffix = f"{parsed['pod_short']}-{parsed['container_id'][:8]}"
    else:
        suffix = "log"
    filename = f"training-{ctx['k8s_job_name']}-{suffix}.log"
    return StreamingResponse(
        history.iter_all_lines(
            cluster_tag=ctx["cluster_tag"], cluster_arn=ctx["cluster_arn"], stream=stream
        ),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# 推理 历史日志 (CloudWatch) — 停止/终态后查 (照训练, 多 pod tab)
# ============================================================


async def _resolve_inf_log_ctx(
    id_: str, current_user: dict[str, Any]
) -> dict[str, Any]:
    """inference id → dict(k8s_endpoint_name/cluster_tag/cluster_arn + 缓存所需字段).

    成员闸门: 非该 inference 所属 ws 的成员/超管一律 403。
    透出 kueue_status/workspace_id/resource_id/cached_log_streams 给 log-streams
    端点接懒加载缓存 (避免再查一次 inf 行)。
    """
    inf = await inf_crud.get(None, id_)
    if inf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"inference not found: {id_}")
    await assert_ws_member(str(inf.get("workspace_id")), current_user)
    cluster_tag, cluster_arn = await _resolve_cluster_log_target(inf.get("workspace_id"))
    return {
        "k8s_endpoint_name": str(inf.get("k8s_endpoint_name") or ""),
        "cluster_tag": cluster_tag,
        "cluster_arn": cluster_arn,
        "kueue_status": inf.get("kueue_status"),
        "workspace_id": str(inf.get("workspace_id") or ""),
        "resource_id": str(inf.get("id") or ""),
        "cached_log_streams": inf.get("log_streams"),
    }


def _assert_inf_stream_belongs(k8s_endpoint_name: str, stream: str) -> None:
    """stream 必须属于本 endpoint (前缀匹配), 否则 403 防越权读别的推理。"""
    if not stream.startswith(inference_stream_prefix(k8s_endpoint_name)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "stream does not belong to this inference"
        )


@logs_router.get(
    "/inferences/{id}/log-streams",
    response_model=list[HistoryStreamInfo],
    summary="列出推理服务的历史 log stream (前端 tab)",
    description=(
        "枚举推理服务在 CloudWatch 里的 main 容器 log streams, 每个 stream 对应前端一个"
        "历史日志 tab (多 replica / 重启会产生多个 stream):\n\n"
        "- **数据源**: CloudWatch Logs `DescribeLogStreams` (通过 `stream_naming.inference_stream_prefix` 按 endpoint 前缀过滤)\n"
        "- **懒加载缓存**: 推理终态后首次列出会写回 DDB `log_streams` (仅 ≤400 条时写), 后续命中缓存\n"
        "- 返回 stream 名 + first/last event 时间, 供前端排序展示 tab\n\n"
        "仅只读, 仅该推理所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理服务不存在"},
        502: {"description": "CloudWatch log group 不存在 (集群未开日志 / 尚未产日志)"},
    },
)
async def inference_log_streams(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[HistoryStreamInfo]:
    ctx = await _resolve_inf_log_ctx(id, current_user)
    try:
        return await history.get_or_cache_streams(
            cached_log_streams=ctx["cached_log_streams"],
            kueue_status=ctx["kueue_status"],
            workspace_id=ctx["workspace_id"],
            resource_id=ctx["resource_id"],
            resource_type=tables.RESOURCE_TYPE_INFERENCE,
            list_fn=history.list_inference_streams,
            list_fn_kwargs={
                "k8s_endpoint_name": ctx["k8s_endpoint_name"],
                "cluster_tag": ctx["cluster_tag"],
                "cluster_arn": ctx["cluster_arn"],
            },
        )
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/inferences/{id}/logs/history",
    response_model=HistoryLogPage,
    summary="翻页/搜索推理单个 stream 的历史日志",
    description=(
        "单个推理 stream (= 前端一个 tab) 内的历史日志翻页 / 搜索, 逻辑与训练同构:\n\n"
        "- **无 query** → CloudWatch `GetLogEvents` 浏览态, 双向翻页 (`load_dir=forward/backward`, `anchor=newest/oldest`)\n"
        "- **有 query** → CloudWatch `FilterLogEvents` 搜索态, 恒旧→新单向, `next_token` 下滑\n"
        "- **stream 前缀校验**: 必须以 `inference_stream_prefix(k8s_endpoint_name)` 开头, 否则 403\n\n"
        "浏览与搜索 `token` 语义不同, 切换条件时需清空 token.\n\n"
        "仅只读, 仅该推理所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "filter pattern 语法错误"},
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 endpoint"},
        404: {"description": "推理服务不存在"},
        409: {"description": "翻页 token 失效, 前端需清 token 重查"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def inference_logs_history(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    token: str | None = Query(default=None, description="next_token from prior page"),
    query: str = Query(default="", description="搜索词 (空=不按内容过滤)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒, 可选)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒, 可选)"),
    load_dir: str | None = Query(
        default=None,
        pattern="^(forward|backward)$",
        description="浏览态翻页方向: 空=首屏; forward=下滑追更新; backward=上滑看更早。搜索态忽略。",
    ),
    anchor: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="浏览首屏定位端: newest=最新; oldest=最早。搜索态忽略。",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=history.HISTORY_LIMIT_MAX,
        description=(
            "浏览态每页条数 (仅无 query 时生效; 搜索态忽略)。"
            "留空 = 按场景默认 500 (首屏 / 翻页同值, 供页面查看)。"
            "coding agent 可显式传大值 (≤10000) 一次性拉大量, 减少翻页; "
            "受单请求最多累积 10 页 + GetLogEvents 单页 ≤1MB 约束, 实际可能少于所要条数。"
        ),
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryLogPage:
    """单 inference stream 历史日志翻页 / 搜索 (逻辑同训练 training_logs_history)。"""
    ctx = await _resolve_inf_log_ctx(id, current_user)
    _assert_inf_stream_belongs(ctx["k8s_endpoint_name"], stream)
    use_search = bool(query.strip())
    try:
        if use_search:
            return await history.search_page(
                cluster_tag=ctx["cluster_tag"],
                cluster_arn=ctx["cluster_arn"],
                stream=stream,
                query=query,
                is_regex=is_regex,
                start_ms=start_ms,
                end_ms=end_ms,
                token=token,
            )
        return await history.fetch_page(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            stream=stream,
            token=token,
            load_dir=load_dir,
            anchor=anchor,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )
    except FilterPatternError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidPageTokenError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            t("logs.page_token_invalid"),
        ) from exc
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/inferences/{id}/logs/history/download",
    summary="下载推理单个 stream 的完整历史日志为文本",
    description=(
        "把推理服务单个 stream 的**完整历史日志**打成 `text/plain` 文件下载:\n\n"
        "- **数据源**: CloudWatch Logs `GetLogEvents` 循环拉全 (生成器流式写响应)\n"
        "- 文件名带 `pod_short + container_id[:8]`, 区分多 replica / 重启\n"
        "- **stream 前缀校验**: 必须属于本 endpoint\n"
        "- **鉴权走 query token** (下载走浏览器 `<a href>`)\n\n"
        "仅只读, 仅该推理所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 endpoint"},
        404: {"description": "推理服务不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def inference_logs_history_download(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    ctx = await _resolve_inf_log_ctx(id, current_user)
    name = ctx["k8s_endpoint_name"]
    _assert_inf_stream_belongs(name, stream)
    parsed = parse_inference_stream_name(stream, name)
    suffix = (
        f"{parsed['pod_short']}-{parsed['container_id'][:8]}" if parsed else "log"
    )
    filename = f"inference-{name}-{suffix}.log"
    return StreamingResponse(
        history.iter_all_lines(
            cluster_tag=ctx["cluster_tag"], cluster_arn=ctx["cluster_arn"], stream=stream
        ),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@logs_router.get(
    "/inferences/{id}/logs/search-all",
    response_model=WholeTaskSearchResult,
    summary="整任务搜索: 跨推理所有 pod 的日志 (Insights)",
    description=(
        "**整推理 (whole-task) 日志搜索**: 一次性跨该 endpoint 名下所有 pod 的主容器日志:\n\n"
        "- **数据源**: CloudWatch Logs Insights (`search_whole_inference_logs`), 同步执行 + 轮询\n"
        "- 圈定范围: 用 `@logStream` 前缀 (`inference_stream_prefix(endpoint)`) 圈全部 replica + 只主容器 + 可选正文关键字 / 正则\n"
        "- 时间窗默认近 24h → now (unix 毫秒)\n"
        "- **单次上限 1 万行**, 命中封顶时 `truncated=true`\n\n"
        "仅只读, 仅该推理所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "Insights query 参数非法 (时间窗 / 正则语法错误)"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "推理服务不存在"},
        502: {"description": "CloudWatch / cluster 未挂日志"},
    },
)
async def inference_logs_search_all(
    id: str,  # noqa: A002
    query: str = Query(default="", description="搜索词 (空=整任务全部日志)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒; 默认近24h)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒; 默认 now)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WholeTaskSearchResult:
    """推理整任务 (跨所有 pod) 日志搜索。走 Logs Insights, 用 @logStream 前缀圈定
    该 endpoint 所有 pod + 只主容器 + 可选关键字/正则。单次最多 1 万行, 达上限 →
    truncated=True。"""
    ctx = await _resolve_inf_log_ctx(id, current_user)
    try:
        return await search_whole_inference_logs(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            endpoint_name=ctx["k8s_endpoint_name"],
            query=query,
            is_regex=is_regex,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InsightsQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


# ============================================================
# Dynamo 多机推理 历史日志 (CloudWatch) — 照推理, 跨 frontend + worker pod tab
# ============================================================


async def _resolve_dynamo_log_ctx(
    id_: str, current_user: dict[str, Any]
) -> dict[str, Any]:
    """dynamo id → dict(k8s_cr_name/cluster_tag/cluster_arn + 缓存所需字段).

    成员闸门: 非该 dynamo 所属 ws 的成员/超管一律 403。
    透出 kueue_status/workspace_id/resource_id/cached_log_streams 给 log-streams
    端点接懒加载缓存 (避免再查一次 dynamo 行)。
    """
    dyn = await dyn_crud.get(None, id_)
    if dyn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dynamo not found: {id_}")
    await assert_ws_member(str(dyn.get("workspace_id")), current_user)
    cluster_tag, cluster_arn = await _resolve_cluster_log_target(dyn.get("workspace_id"))
    return {
        "k8s_cr_name": str(dyn.get("k8s_cr_name") or ""),
        "cluster_tag": cluster_tag,
        "cluster_arn": cluster_arn,
        "kueue_status": dyn.get("kueue_status"),
        "workspace_id": str(dyn.get("workspace_id") or ""),
        "resource_id": str(dyn.get("id") or ""),
        "cached_log_streams": dyn.get("log_streams"),
    }


def _assert_dynamo_stream_belongs(k8s_cr_name: str, stream: str) -> None:
    """stream 必须属于本 dynamo CR (前缀匹配), 否则 403 防越权读别的任务。"""
    if not stream.startswith(dynamo_stream_prefix(k8s_cr_name)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "stream does not belong to this dynamo inference"
        )


@logs_router.get(
    "/dynamo-inferences/{id}/log-streams",
    response_model=list[HistoryStreamInfo],
    summary="列出 Dynamo 多机推理的历史 log stream (前端 tab)",
    include_in_schema=False,
    description=(
        "枚举 Dynamo 多机推理在 CloudWatch 里的 main 容器 log streams (跨 frontend + 所有 worker pod):\n\n"
        "- **数据源**: CloudWatch Logs `DescribeLogStreams` (通过 `stream_naming.dynamo_stream_prefix` 按 CR 名前缀过滤)\n"
        "- **懒加载缓存**: 终态后首次列出会写回 DDB `log_streams` (仅 ≤400 条时写), 后续命中缓存\n"
        "- 前端一个 tab = 一个 stream (frontend pod / 每个 worker pod 各一份)\n\n"
        "仅只读, 仅该 dynamo 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Dynamo 推理不存在"},
        502: {"description": "CloudWatch log group 不存在 (集群未开日志 / 尚未产日志)"},
    },
)
async def dynamo_log_streams(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[HistoryStreamInfo]:
    ctx = await _resolve_dynamo_log_ctx(id, current_user)
    try:
        return await history.get_or_cache_streams(
            cached_log_streams=ctx["cached_log_streams"],
            kueue_status=ctx["kueue_status"],
            workspace_id=ctx["workspace_id"],
            resource_id=ctx["resource_id"],
            resource_type=tables.RESOURCE_TYPE_DYNAMO,
            list_fn=history.list_dynamo_streams,
            list_fn_kwargs={
                "k8s_cr_name": ctx["k8s_cr_name"],
                "cluster_tag": ctx["cluster_tag"],
                "cluster_arn": ctx["cluster_arn"],
            },
        )
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/dynamo-inferences/{id}/logs/history",
    response_model=HistoryLogPage,
    summary="翻页/搜索 Dynamo 单个 stream 的历史日志",
    include_in_schema=False,
    description=(
        "单个 Dynamo stream (= 前端一个 tab, frontend 或某个 worker pod) 内的历史日志翻页 / 搜索, 逻辑同训练/推理:\n\n"
        "- **无 query** → CloudWatch `GetLogEvents` 浏览态, 双向翻页 (`load_dir`, `anchor`)\n"
        "- **有 query** → CloudWatch `FilterLogEvents` 搜索态, 恒旧→新单向\n"
        "- **stream 前缀校验**: 必须以 `dynamo_stream_prefix(k8s_cr_name)` 开头, 否则 403\n\n"
        "仅只读, 仅该 dynamo 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "filter pattern 语法错误"},
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 dynamo CR"},
        404: {"description": "Dynamo 推理不存在"},
        409: {"description": "翻页 token 失效, 前端需清 token 重查"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def dynamo_logs_history(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    token: str | None = Query(default=None, description="next_token from prior page"),
    query: str = Query(default="", description="搜索词 (空=不按内容过滤)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒, 可选)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒, 可选)"),
    load_dir: str | None = Query(
        default=None,
        pattern="^(forward|backward)$",
        description="浏览态翻页方向: 空=首屏; forward=下滑追更新; backward=上滑看更早。搜索态忽略。",
    ),
    anchor: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="浏览首屏定位端: newest=最新; oldest=最早。搜索态忽略。",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=history.HISTORY_LIMIT_MAX,
        description=(
            "浏览态每页条数 (仅无 query 时生效; 搜索态忽略)。"
            "留空 = 按场景默认 500 (首屏 / 翻页同值, 供页面查看)。"
            "coding agent 可显式传大值 (≤10000) 一次性拉大量, 减少翻页; "
            "受单请求最多累积 10 页 + GetLogEvents 单页 ≤1MB 约束, 实际可能少于所要条数。"
        ),
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryLogPage:
    """单 dynamo stream 历史日志翻页 / 搜索 (逻辑同训练/推理)。"""
    ctx = await _resolve_dynamo_log_ctx(id, current_user)
    _assert_dynamo_stream_belongs(ctx["k8s_cr_name"], stream)
    use_search = bool(query.strip())
    try:
        if use_search:
            return await history.search_page(
                cluster_tag=ctx["cluster_tag"],
                cluster_arn=ctx["cluster_arn"],
                stream=stream,
                query=query,
                is_regex=is_regex,
                start_ms=start_ms,
                end_ms=end_ms,
                token=token,
            )
        return await history.fetch_page(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            stream=stream,
            token=token,
            load_dir=load_dir,
            anchor=anchor,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )
    except FilterPatternError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidPageTokenError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            t("logs.page_token_invalid"),
        ) from exc
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/dynamo-inferences/{id}/logs/history/download",
    summary="下载 Dynamo 单个 stream 的完整历史日志为文本",
    include_in_schema=False,
    description=(
        "把 Dynamo 单个 stream 的**完整历史日志**打成 `text/plain` 文件下载:\n\n"
        "- **数据源**: CloudWatch Logs `GetLogEvents` 循环拉全 (生成器流式)\n"
        "- 文件名带 `pod_short + container_id[:8]`, 区分 frontend / 各 worker pod / 重启\n"
        "- **stream 前缀校验**: 必须属于本 dynamo CR\n"
        "- **鉴权走 query token** (下载走浏览器 `<a href>`)\n\n"
        "仅只读, 仅该 dynamo 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 dynamo CR"},
        404: {"description": "Dynamo 推理不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def dynamo_logs_history_download(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    ctx = await _resolve_dynamo_log_ctx(id, current_user)
    name = ctx["k8s_cr_name"]
    _assert_dynamo_stream_belongs(name, stream)
    parsed = parse_dynamo_stream_name(stream)
    suffix = (
        f"{parsed['pod_short']}-{parsed['container_id'][:8]}" if parsed else "log"
    )
    filename = f"dynamo-{name}-{suffix}.log"
    return StreamingResponse(
        history.iter_all_lines(
            cluster_tag=ctx["cluster_tag"], cluster_arn=ctx["cluster_arn"], stream=stream
        ),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@logs_router.get(
    "/dynamo-inferences/{id}/logs/search-all",
    response_model=WholeTaskSearchResult,
    summary="整任务搜索: 跨 Dynamo 所有 pod 的日志 (Insights)",
    include_in_schema=False,
    description=(
        "**整 Dynamo (whole-task) 日志搜索**: 一次性跨 frontend + 所有 worker pod 的主容器 `main` 日志:\n\n"
        "- **数据源**: CloudWatch Logs Insights (`search_whole_dynamo_logs`), 同步执行 + 轮询\n"
        "- 圈定范围: 用 `@logStream` 前缀 (`dynamo_stream_prefix(k8s_cr_name)`) 圈整 CR 全部 pod + 只主容器 `main` + 可选正文关键字 / 正则\n"
        "- 时间窗默认近 24h → now (unix 毫秒)\n"
        "- **单次上限 1 万行**, 命中封顶时 `truncated=true`\n\n"
        "仅只读, 仅该 dynamo 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "Insights query 参数非法 (时间窗 / 正则语法错误)"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Dynamo 推理不存在"},
        502: {"description": "CloudWatch / cluster 未挂日志"},
    },
)
async def dynamo_logs_search_all(
    id: str,  # noqa: A002
    query: str = Query(default="", description="搜索词 (空=整任务全部日志)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒; 默认近24h)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒; 默认 now)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WholeTaskSearchResult:
    """Dynamo 整任务 (跨 frontend + 所有 worker pod) 日志搜索。走 Logs Insights,
    用 @logStream 前缀圈定该 CR 所有 pod + 只主容器 "main" + 可选关键字/正则。
    单次最多 1 万行, 达上限 → truncated=True。"""
    ctx = await _resolve_dynamo_log_ctx(id, current_user)
    try:
        return await search_whole_dynamo_logs(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            k8s_cr_name=ctx["k8s_cr_name"],
            query=query,
            is_regex=is_regex,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InsightsQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


# ============================================================
# Ray (rayjob) 历史日志 (CloudWatch) — 照 dynamo, 跨 head + 所有 worker pod tab
# ============================================================


async def _resolve_ray_log_ctx(
    id_: str, current_user: dict[str, Any]
) -> dict[str, Any]:
    """rayjob id → dict(ray_cluster_name/cluster_tag/cluster_arn + 缓存字段)。

    成员闸门: 非该 rayjob 所属 ws 的成员/超管一律 403。
    ⚠️ stream 前缀锚点是 ray_cluster_name (= CR.status.rayClusterName，带随机后缀，
    非 CR 名)，由 sync 回填进 DDB metadata.ray_cluster_name。
    """
    ray = await ray_crud.get(None, id_)
    if ray is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id_}")
    await assert_ws_member(str(ray.get("workspace_id")), current_user)
    cluster_tag, cluster_arn = await _resolve_cluster_log_target(ray.get("workspace_id"))
    return {
        "ray_cluster_name": str(ray.get("ray_cluster_name") or ""),
        "cluster_tag": cluster_tag,
        "cluster_arn": cluster_arn,
        "kueue_status": ray.get("kueue_status"),
        "workspace_id": str(ray.get("workspace_id") or ""),
        "resource_id": str(ray.get("id") or ""),
        "cached_log_streams": ray.get("log_streams"),
    }


def _assert_ray_stream_belongs(ray_cluster_name: str, stream: str) -> None:
    """stream 必须属于本 Ray 任务 (前缀匹配)，否则 403 防越权读别的任务。"""
    if not ray_cluster_name or not stream.startswith(ray_stream_prefix(ray_cluster_name)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "stream does not belong to this rayjob"
        )


@logs_router.get(
    "/rayjobs/{id}/log-streams",
    response_model=list[HistoryStreamInfo],
    summary="列出 Ray 任务的历史 log stream (前端 tab)",
    description=(
        "枚举 Ray (rayjob) 在 CloudWatch 里的 head/worker 主容器 log streams:\n\n"
        "- **数据源**: CloudWatch `DescribeLogStreams` (按 rayClusterName 前缀过滤)\n"
        "- **懒加载缓存**: 终态后首次列出会写回 DDB `log_streams`\n"
        "- 前端一个 tab = 一个 stream (head pod / 每个 worker pod 各一份)\n"
        "- head pod 另有 driver 日志 stream (driver-log-tailer sidecar): "
        "转写 job-driver-*.log, 即用户训练脚本 print 输出\n\n"
        "仅只读, 仅该 rayjob 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Ray 任务不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def ray_log_streams(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[HistoryStreamInfo]:
    ctx = await _resolve_ray_log_ctx(id, current_user)
    try:
        return await history.get_or_cache_streams(
            cached_log_streams=ctx["cached_log_streams"],
            kueue_status=ctx["kueue_status"],
            workspace_id=ctx["workspace_id"],
            resource_id=ctx["resource_id"],
            resource_type=tables.RESOURCE_TYPE_RAYJOB,
            list_fn=history.list_ray_streams,
            list_fn_kwargs={
                "ray_cluster_name": ctx["ray_cluster_name"],
                "cluster_tag": ctx["cluster_tag"],
                "cluster_arn": ctx["cluster_arn"],
            },
        )
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/rayjobs/{id}/logs/history",
    response_model=HistoryLogPage,
    summary="翻页/搜索 Ray 单个 stream 的历史日志",
    description=(
        "单个 Ray stream (= 前端一个 tab, head 或某 worker pod) 内的历史日志翻页 / 搜索:\n\n"
        "- **无 query** → `GetLogEvents` 浏览态双向翻页\n"
        "- **有 query** → `FilterLogEvents` 搜索态\n"
        "- **stream 前缀校验**: 必须以 rayClusterName 前缀开头, 否则 403\n\n"
        "仅只读, 仅该 rayjob 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "filter pattern 语法错误"},
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 rayjob"},
        404: {"description": "Ray 任务不存在"},
        409: {"description": "翻页 token 失效"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def ray_logs_history(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    token: str | None = Query(default=None, description="next_token from prior page"),
    query: str = Query(default="", description="搜索词 (空=不按内容过滤)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒, 可选)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒, 可选)"),
    load_dir: str | None = Query(
        default=None,
        pattern="^(forward|backward)$",
        description="浏览态翻页方向: 空=首屏; forward=下滑追更新; backward=上滑看更早。",
    ),
    anchor: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="浏览首屏定位端: newest=最新; oldest=最早。",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=history.HISTORY_LIMIT_MAX,
        description="浏览态每页条数 (留空=首屏1000/翻页200; ≤10000)。",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryLogPage:
    ctx = await _resolve_ray_log_ctx(id, current_user)
    _assert_ray_stream_belongs(ctx["ray_cluster_name"], stream)
    use_search = bool(query.strip())
    try:
        if use_search:
            return await history.search_page(
                cluster_tag=ctx["cluster_tag"],
                cluster_arn=ctx["cluster_arn"],
                stream=stream,
                query=query,
                is_regex=is_regex,
                start_ms=start_ms,
                end_ms=end_ms,
                token=token,
            )
        return await history.fetch_page(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            stream=stream,
            token=token,
            load_dir=load_dir,
            anchor=anchor,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )
    except FilterPatternError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidPageTokenError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, t("logs.page_token_invalid")
        ) from exc
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/rayjobs/{id}/logs/history/download",
    summary="下载 Ray 单个 stream 的完整历史日志为文本",
    description=(
        "把 Ray 单个 stream 的完整历史日志打成 `text/plain` 下载:\n\n"
        "- **数据源**: `GetLogEvents` 循环拉全\n"
        "- 文件名带 pod_short + container_id[:8]\n"
        "- **鉴权走 query token**\n\n"
        "仅只读, 仅该 rayjob 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 rayjob"},
        404: {"description": "Ray 任务不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def ray_logs_history_download(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    ctx = await _resolve_ray_log_ctx(id, current_user)
    name = ctx["ray_cluster_name"]
    _assert_ray_stream_belongs(name, stream)
    parsed = parse_ray_stream_name(stream)
    suffix = (
        f"{parsed['pod_short']}-{parsed['container_id'][:8]}" if parsed else "log"
    )
    filename = f"rayjob-{name}-{suffix}.log"
    return StreamingResponse(
        history.iter_all_lines(
            cluster_tag=ctx["cluster_tag"], cluster_arn=ctx["cluster_arn"], stream=stream
        ),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@logs_router.get(
    "/rayjobs/{id}/logs/search-all",
    response_model=WholeTaskSearchResult,
    summary="整任务搜索: 跨 Ray 所有 pod 的日志 (Insights)",
    description=(
        "**整 Ray 任务日志搜索**: 一次性跨 head + 所有 worker pod 的主容器日志:\n\n"
        "- **数据源**: CloudWatch Logs Insights (`search_whole_ray_logs`)\n"
        "- 圈定: `@logStream` 前缀 (rayClusterName) + 主容器 ray-head/ray-worker + 可选关键字/正则\n"
        "- 时间窗默认近 24h → now; **单次上限 1 万行**\n"
        "- ⚠️ 只含 Ray 系统日志; 用户脚本 print 不在 CloudWatch\n\n"
        "仅只读, 仅该 rayjob 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "Insights query 参数非法"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Ray 任务不存在"},
        502: {"description": "CloudWatch / cluster 未挂日志"},
    },
)
async def ray_logs_search_all(
    id: str,  # noqa: A002
    query: str = Query(default="", description="搜索词 (空=整任务全部日志)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒; 默认近24h)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒; 默认 now)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WholeTaskSearchResult:
    ctx = await _resolve_ray_log_ctx(id, current_user)
    try:
        return await search_whole_ray_logs(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            ray_cluster_name=ctx["ray_cluster_name"],
            query=query,
            is_regex=is_regex,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InsightsQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


# ── Ray driver 日志 (实时, exec cat head 的 job-driver-*.log) ──
# CloudWatch 只采容器 stdout, 而 driver (entrypoint 真输出) 被 Ray 重定向进
# head 上的文件, 不进任何容器 stdout → 只能 exec 进 head cat 出来。pod 活时可看。
@logs_router.get(
    "/rayjobs/{id}/driver-logs",
    summary="实时读 Ray 训练脚本输出 (driver 日志, exec head)",
    description=(
        "exec 进 head pod `cat /tmp/ray/session_latest/logs/job-driver-*.log` — "
        "这才是**用户 entrypoint 的真输出** (loss/print/task 分发)。\n\n"
        "- CloudWatch 与容器 stdout 都**没有**它 (Ray 把 driver stdout 重定向进文件)\n"
        "- 仅 head pod 有; pod 存活时可读, 回收后即失\n"
        "- 返回 `{text, found}`; `found=false` = entrypoint 未开始 / head 已回收\n\n"
        "仅只读, 仅该 rayjob 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Ray 任务不存在"},
    },
)
async def ray_driver_logs(
    id: str,  # noqa: A002
    pod: str = Query(..., description="head pod name (从详情 pods 里 role=head 那个拿)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    row = await ray_crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    namespace = row.get("k8s_namespace") or "default"
    out = await K8sClient().exec_in_pod(
        namespace=namespace,
        pod_name=pod,
        container="ray-head",
        command=[
            "sh",
            "-c",
            "cat /tmp/ray/session_latest/logs/job-driver-*.log 2>/dev/null",
        ],
        timeout=10,
    )
    return {"text": out or "", "found": bool(out)}


# ── Ray 容器实时日志 (SSE, kubectl logs --follow; 照训练 /training-jobs 那套) ──
# 容器 stdout = Ray 系统守护进程 (raylet/GCS/dashboard), 非训练脚本输出。
@logs_router.get(
    "/rayjobs/{id}/logs/stream",
    summary="实时 SSE 推送 Ray Pod 容器 stdout (系统日志)",
    description=(
        "SSE 流式推单个 Ray Pod 的容器 stdout (kubectl logs --follow, Pod 活才用):\n\n"
        "- **数据源**: 容器主进程 stdout = Ray 守护进程 (raylet/GCS/dashboard), **非训练脚本输出** "
        "(训练输出走 `/rayjobs/{id}/driver-logs`)\n"
        "- 事件: `open` / `log` / `error` / `close`\n"
        "- `pod` 必传; `container` 默认 `ray-head` (worker 传 `ray-worker`)\n"
        "- 鉴权走 query token (EventSource 无法自定义 Header)\n\n"
        "Pod 死后转用 CloudWatch 历史 (`/rayjobs/{id}/logs/history`)."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Ray 任务不存在"},
    },
)
async def ray_logs_stream(
    id: str,  # noqa: A002
    pod: str = Query(..., description="Pod name (从详情 pods 拿)"),
    container: str = Query(default="ray-head", description="head=ray-head / worker=ray-worker"),
    tail_lines: int = Query(default=200, ge=0, le=10000),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    row = await ray_crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    namespace = row.get("k8s_namespace") or "default"

    async def _gen() -> AsyncIterator[bytes]:
        yield _sse_event({"type": "open", "pod": pod, "ts": int(time.time() * 1000)}).encode()
        try:
            async for line in K8sClient().stream_pod_logs(
                namespace=namespace,
                pod_name=pod,
                container=container,
                tail_lines=tail_lines,
            ):
                yield _sse_event(
                    {"type": "log", "ts": int(time.time() * 1000), "line": line, "pod": pod}
                ).encode()
        except Exception as exc:  # noqa: BLE001
            logger.info("logs.ray.stream.fail", id=id, pod=pod, err=str(exc))
            yield _sse_event({"type": "error", "msg": str(exc)}).encode()
        finally:
            yield _sse_event({"type": "close"}).encode()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ============================================================
# llm-d 多机推理 历史日志 (CloudWatch) — 照 dynamo, 跨 LWS worker + gateway pod tab
# ============================================================


async def _resolve_llmd_log_ctx(
    id_: str, current_user: dict[str, Any]
) -> dict[str, Any]:
    """llmd id → dict(k8s_name/cluster_tag/cluster_arn + 缓存所需字段).

    成员闸门: 非该 llmd 所属 ws 的成员/超管一律 403。
    透出 kueue_status/workspace_id/resource_id/cached_log_streams 给 log-streams
    端点接懒加载缓存 (避免再查一次 llmd 行)。
    """
    llmd = await llmd_crud.get(None, id_)
    if llmd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"llmd not found: {id_}")
    await assert_ws_member(str(llmd.get("workspace_id")), current_user)
    cluster_tag, cluster_arn = await _resolve_cluster_log_target(
        llmd.get("workspace_id")
    )
    return {
        "k8s_name": str(llmd.get("k8s_name") or ""),
        "cluster_tag": cluster_tag,
        "cluster_arn": cluster_arn,
        "kueue_status": llmd.get("kueue_status"),
        "workspace_id": str(llmd.get("workspace_id") or ""),
        "resource_id": str(llmd.get("id") or ""),
        "cached_log_streams": llmd.get("log_streams"),
    }


def _assert_llmd_stream_belongs(k8s_name: str, stream: str) -> None:
    """stream 必须属于本 llmd CR (前缀匹配), 否则 403 防越权读别的任务。"""
    if not stream.startswith(llmd_stream_prefix(k8s_name)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "stream does not belong to this llm-d inference"
        )


@logs_router.get(
    "/llmd/{id}/log-streams",
    response_model=list[HistoryStreamInfo],
    summary="列出 llm-d 多机推理的历史 log stream (前端 tab)",
    description=(
        "枚举 llm-d 在 CloudWatch 里的主容器 log streams (跨 LWS worker + gateway 所有 pod):\n\n"
        "- **数据源**: CloudWatch Logs `DescribeLogStreams` (通过 `stream_naming.llmd_stream_prefix` 按 CR base 名前缀过滤)\n"
        "- **懒加载缓存**: 终态后首次列出会写回 DDB `log_streams` (仅 ≤400 条时写), 后续命中缓存\n"
        "- 前端一个 tab = 一个 stream (leader / worker / gateway 各副本各一份, 排除 otel sidecar)\n\n"
        "仅只读, 仅该 llmd 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "llm-d 推理不存在"},
        502: {"description": "CloudWatch log group 不存在 (集群未开日志 / 尚未产日志)"},
    },
)
async def llmd_log_streams(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[HistoryStreamInfo]:
    ctx = await _resolve_llmd_log_ctx(id, current_user)
    try:
        return await history.get_or_cache_streams(
            cached_log_streams=ctx["cached_log_streams"],
            kueue_status=ctx["kueue_status"],
            workspace_id=ctx["workspace_id"],
            resource_id=ctx["resource_id"],
            resource_type=tables.RESOURCE_TYPE_LLMD,
            list_fn=history.list_llmd_streams,
            list_fn_kwargs={
                "k8s_name": ctx["k8s_name"],
                "cluster_tag": ctx["cluster_tag"],
                "cluster_arn": ctx["cluster_arn"],
            },
        )
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/llmd/{id}/logs/history",
    response_model=HistoryLogPage,
    summary="翻页/搜索 llm-d 单个 stream 的历史日志",
    description=(
        "单个 llm-d stream (= 前端一个 tab, 某个 worker 或 gateway pod) 内的历史日志翻页 / 搜索, 逻辑同训练/推理:\n\n"
        "- **无 query** → CloudWatch `GetLogEvents` 浏览态, 双向翻页 (`load_dir`, `anchor`)\n"
        "- **有 query** → CloudWatch `FilterLogEvents` 搜索态, 恒旧→新单向\n"
        "- **stream 前缀校验**: 必须以 `llmd_stream_prefix(k8s_name)` 开头, 否则 403\n\n"
        "仅只读, 仅该 llmd 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "filter pattern 语法错误"},
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 llm-d CR"},
        404: {"description": "llm-d 推理不存在"},
        409: {"description": "翻页 token 失效, 前端需清 token 重查"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def llmd_logs_history(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    token: str | None = Query(default=None, description="next_token from prior page"),
    query: str = Query(default="", description="搜索词 (空=不按内容过滤)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒, 可选)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒, 可选)"),
    load_dir: str | None = Query(
        default=None,
        pattern="^(forward|backward)$",
        description="浏览态翻页方向: 空=首屏; forward=下滑追更新; backward=上滑看更早。搜索态忽略。",
    ),
    anchor: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="浏览首屏定位端: newest=最新; oldest=最早。搜索态忽略。",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryLogPage:
    """单 llm-d stream 历史日志翻页 / 搜索 (逻辑同训练/推理/dynamo)。"""
    ctx = await _resolve_llmd_log_ctx(id, current_user)
    _assert_llmd_stream_belongs(ctx["k8s_name"], stream)
    use_search = bool(query.strip())
    try:
        if use_search:
            return await history.search_page(
                cluster_tag=ctx["cluster_tag"],
                cluster_arn=ctx["cluster_arn"],
                stream=stream,
                query=query,
                is_regex=is_regex,
                start_ms=start_ms,
                end_ms=end_ms,
                token=token,
            )
        return await history.fetch_page(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            stream=stream,
            token=token,
            load_dir=load_dir,
            anchor=anchor,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except FilterPatternError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidPageTokenError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            t("logs.page_token_invalid"),
        ) from exc
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/llmd/{id}/logs/history/download",
    summary="下载 llm-d 单个 stream 的完整历史日志为文本",
    description=(
        "把 llm-d 单个 stream 的**完整历史日志**打成 `text/plain` 文件下载:\n\n"
        "- **数据源**: CloudWatch Logs `GetLogEvents` 循环拉全 (生成器流式)\n"
        "- 文件名带 `pod_short + container_id[:8]`, 区分 worker / gateway / 各副本\n"
        "- **stream 前缀校验**: 必须属于本 llm-d CR\n"
        "- **鉴权走 query token** (下载走浏览器 `<a href>`)\n\n"
        "仅只读, 仅该 llmd 所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本 llm-d CR"},
        404: {"description": "llm-d 推理不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def llmd_logs_history_download(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    ctx = await _resolve_llmd_log_ctx(id, current_user)
    name = ctx["k8s_name"]
    _assert_llmd_stream_belongs(name, stream)
    parsed = parse_llmd_stream_name(stream)
    suffix = (
        f"{parsed['pod_short']}-{parsed['container_id'][:8]}" if parsed else "log"
    )
    filename = f"llmd-{name}-{suffix}.log"
    return StreamingResponse(
        history.iter_all_lines(
            cluster_tag=ctx["cluster_tag"], cluster_arn=ctx["cluster_arn"], stream=stream
        ),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@logs_router.get(
    "/llmd/{id}/logs/search-all",
    response_model=WholeTaskSearchResult,
    summary="整任务搜索: 跨 llm-d 所有 pod 的日志 (Insights)",
    description=(
        "**整 llm-d (whole-task) 日志搜索**: 一次性跨 LWS worker + gateway 所有 pod 的主容器日志:\n\n"
        "- **数据源**: CloudWatch Logs Insights (`search_whole_llmd_logs`), 同步执行 + 轮询\n"
        "- 圈定范围: 用 `@logStream` 前缀 (`llmd_stream_prefix(k8s_name)`) 圈整任务全部 pod + 双容器 (`sglang` + `gateway`) + 可选正文关键字 / 正则\n"
        "- 时间窗默认近 24h → now (unix 毫秒)\n"
        "- **单次上限 1 万行**, 命中封顶时 `truncated=true`\n\n"
        "仅只读, 仅该 llmd 所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "Insights query 参数非法 (时间窗 / 正则语法错误)"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "llm-d 推理不存在"},
        502: {"description": "CloudWatch / cluster 未挂日志"},
    },
)
async def llmd_logs_search_all(
    id: str,  # noqa: A002
    query: str = Query(default="", description="搜索词 (空=整任务全部日志)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒; 默认近24h)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒; 默认 now)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WholeTaskSearchResult:
    """llm-d 整任务 (跨 LWS worker + gateway 所有 pod) 日志搜索。走 Logs Insights,
    用 @logStream 前缀圈定该 CR 所有 pod + 双容器 sglang/gateway + 可选关键字/正则。
    单次最多 1 万行, 达上限 → truncated=True。"""
    ctx = await _resolve_llmd_log_ctx(id, current_user)
    try:
        return await search_whole_llmd_logs(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            k8s_name=ctx["k8s_name"],
            query=query,
            is_regex=is_regex,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InsightsQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


# ============================================================
# 开发机 (devinstance / Workspace CR) 历史日志 (CloudWatch) — 照 dynamo, 双容器 workspace/direct-ssh-init
# ============================================================


async def _resolve_devinstance_log_ctx(
    id_: str, current_user: dict[str, Any]
) -> dict[str, Any]:
    """dev id → dict(k8s_workspace_name/cluster_tag/cluster_arn + 缓存所需字段).

    成员闸门: 非该开发机所属 ws 的成员/超管一律 403。
    """
    dev = await dev_crud.get(None, id_)
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dev instance not found: {id_}")
    await assert_ws_member(str(dev.get("workspace_id")), current_user)
    cluster_tag, cluster_arn = await _resolve_cluster_log_target(dev.get("workspace_id"))
    return {
        "k8s_workspace_name": str(dev.get("k8s_workspace_name") or ""),
        "cluster_tag": cluster_tag,
        "cluster_arn": cluster_arn,
        "kueue_status": dev.get("kueue_status"),
        "workspace_id": str(dev.get("workspace_id") or ""),
        "resource_id": str(dev.get("id") or ""),
        "cached_log_streams": dev.get("log_streams"),
    }


def _assert_devinstance_stream_belongs(k8s_workspace_name: str, stream: str) -> None:
    """stream 必须属于本开发机 (前缀匹配), 否则 403 防越权读别的开发机。"""
    if not stream.startswith(devinstance_stream_prefix(k8s_workspace_name)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "stream does not belong to this dev instance"
        )


@logs_router.get(
    "/dev-instances/{id}/log-streams",
    response_model=list[HistoryStreamInfo],
    summary="列出开发机的历史 log stream (前端 tab)",
    description=(
        "枚举开发机在 CloudWatch 里的日志 streams (workspace 主容器 + direct-ssh-init init 容器):\n\n"
        "- **数据源**: CloudWatch `DescribeLogStreams` (按 `workspace-{CR名}` 前缀过滤)\n"
        "- **懒加载缓存**: 终态后首次列出会写回 DDB `log_streams`\n"
        "- 前端一个 tab = 一个 stream (每代 pod 的 workspace / direct-ssh-init 各一份)\n\n"
        "仅只读, 仅该开发机所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def devinstance_log_streams(
    id: str,  # noqa: A002
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[HistoryStreamInfo]:
    ctx = await _resolve_devinstance_log_ctx(id, current_user)
    try:
        return await history.get_or_cache_streams(
            cached_log_streams=ctx["cached_log_streams"],
            kueue_status=ctx["kueue_status"],
            workspace_id=ctx["workspace_id"],
            resource_id=ctx["resource_id"],
            resource_type=tables.RESOURCE_TYPE_DEV,
            list_fn=history.list_devinstance_streams,
            list_fn_kwargs={
                "k8s_workspace_name": ctx["k8s_workspace_name"],
                "cluster_tag": ctx["cluster_tag"],
                "cluster_arn": ctx["cluster_arn"],
            },
        )
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/dev-instances/{id}/logs/history",
    response_model=HistoryLogPage,
    summary="翻页/搜索开发机单个 stream 的历史日志",
    description=(
        "单个开发机 stream 内的历史日志翻页 / 搜索, 逻辑同训练/推理:\n\n"
        "- **无 query** → `GetLogEvents` 浏览态, 双向翻页\n"
        "- **有 query** → `FilterLogEvents` 搜索态, 恒旧→新单向\n"
        "- **stream 前缀校验**: 必须以 `workspace-{CR名}` 开头, 否则 403\n\n"
        "仅只读, 仅该开发机所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "filter pattern 语法错误"},
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本开发机"},
        404: {"description": "开发机不存在"},
        409: {"description": "翻页 token 失效, 前端需清 token 重查"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def devinstance_logs_history(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    token: str | None = Query(default=None, description="next_token from prior page"),
    query: str = Query(default="", description="搜索词 (空=不按内容过滤)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒, 可选)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒, 可选)"),
    load_dir: str | None = Query(
        default=None,
        pattern="^(forward|backward)$",
        description="浏览态翻页方向: 空=首屏; forward=下滑追更新; backward=上滑看更早。搜索态忽略。",
    ),
    anchor: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="浏览首屏定位端: newest=最新; oldest=最早。搜索态忽略。",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=history.HISTORY_LIMIT_MAX,
        description="浏览态每页条数 (仅无 query 时生效; 搜索态忽略)。留空=默认 500。",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryLogPage:
    ctx = await _resolve_devinstance_log_ctx(id, current_user)
    _assert_devinstance_stream_belongs(ctx["k8s_workspace_name"], stream)
    use_search = bool(query.strip())
    try:
        if use_search:
            return await history.search_page(
                cluster_tag=ctx["cluster_tag"],
                cluster_arn=ctx["cluster_arn"],
                stream=stream,
                query=query,
                is_regex=is_regex,
                start_ms=start_ms,
                end_ms=end_ms,
                token=token,
            )
        return await history.fetch_page(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            stream=stream,
            token=token,
            load_dir=load_dir,
            anchor=anchor,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )
    except FilterPatternError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidPageTokenError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            t("logs.page_token_invalid"),
        ) from exc
    except LogGroupNotFoundError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@logs_router.get(
    "/dev-instances/{id}/logs/history/download",
    summary="下载开发机单个 stream 的完整历史日志为文本",
    description=(
        "把开发机单个 stream 的完整历史日志打成 `text/plain` 文件下载。"
        "鉴权走 query token (下载走浏览器 `<a href>`)。仅该开发机所属 ws 的成员或超管可访问."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 stream 不属于本开发机"},
        404: {"description": "开发机不存在"},
        502: {"description": "CloudWatch log group 不存在"},
    },
)
async def devinstance_logs_history_download(
    id: str,  # noqa: A002
    stream: str = Query(..., description="stream_name from /log-streams"),
    current_user: dict[str, Any] = Depends(get_current_user_allow_query),
) -> StreamingResponse:
    ctx = await _resolve_devinstance_log_ctx(id, current_user)
    name = ctx["k8s_workspace_name"]
    _assert_devinstance_stream_belongs(name, stream)
    parsed = parse_devinstance_stream_name(stream)
    suffix = (
        f"{parsed['pod_short']}-{parsed['container_id'][:8]}" if parsed else "log"
    )
    filename = f"devinstance-{name}-{suffix}.log"
    return StreamingResponse(
        history.iter_all_lines(
            cluster_tag=ctx["cluster_tag"], cluster_arn=ctx["cluster_arn"], stream=stream
        ),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@logs_router.get(
    "/dev-instances/{id}/logs/search-all",
    response_model=WholeTaskSearchResult,
    summary="整任务搜索: 跨开发机所有 pod 代次的日志 (Insights)",
    description=(
        "整开发机日志搜索: 跨所有 pod 代次的 workspace + direct-ssh-init 容器日志。"
        "数据源 Logs Insights, 时间窗默认近 24h, 单次上限 1 万行。"
        "仅只读, 仅该开发机所属 ws 的成员或超管可访问."
    ),
    responses={
        400: {"description": "Insights query 参数非法 (时间窗 / 正则语法错误)"},
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "开发机不存在"},
        502: {"description": "CloudWatch / cluster 未挂日志"},
    },
)
async def devinstance_logs_search_all(
    id: str,  # noqa: A002
    query: str = Query(default="", description="搜索词 (空=整开发机全部日志)"),
    is_regex: bool = Query(default=False, description="query 是否按正则解析"),
    start_ms: int | None = Query(default=None, description="时间窗起点 (unix 毫秒; 默认近24h)"),
    end_ms: int | None = Query(default=None, description="时间窗终点 (unix 毫秒; 默认 now)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> WholeTaskSearchResult:
    ctx = await _resolve_devinstance_log_ctx(id, current_user)
    try:
        return await search_whole_devinstance_logs(
            cluster_tag=ctx["cluster_tag"],
            cluster_arn=ctx["cluster_arn"],
            k8s_workspace_name=ctx["k8s_workspace_name"],
            query=query,
            is_regex=is_regex,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    except InsightsQueryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except LogsServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
