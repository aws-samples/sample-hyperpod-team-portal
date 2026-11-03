"""Monitoring REST routes (DDB-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.prometheus import (
    PromAPIError,
)
from app.adapters.prometheus import (
    instant_query as prom_instant_query,
)
from app.adapters.prometheus import (
    range_query as prom_range_query,
)
import time
from typing import Any

from fastapi import Query

from app.core.logging import get_logger
from app.core.security import assert_ws_admin, assert_ws_member, get_current_user
from app.modules.devinstance.persistence import crud as dev_crud
from app.modules.monitoring.api.schemas import (
    GpuUtilizationResponse,
    InstantQueryPayload,
    KueueQueueRow,
    PromResponse,
    QueryTemplate,
    RangeQueryPayload,
)
from app.modules.monitoring.domain.gpu_util import (
    build_gpu_util_queries,
    gpu_util_time_window,
)
from app.modules.monitoring.orchestration import (
    list_kueue_queue_rows,
    resolve_dev_instance_kpi_templates,
    resolve_dev_instance_templates,
    resolve_dynamo_templates,
    resolve_inference_templates,
    resolve_llmd_templates,
    resolve_rayjob_templates,
    resolve_training_templates,
)
from app.modules.dynamo.persistence import crud as dyn_crud
from app.modules.inference.persistence import crud as inf_crud
from app.modules.llmd.persistence import crud as llmd_crud
from app.modules.rayjob.persistence import crud as rayjob_crud
from app.modules.training.persistence import crud as train_crud
from app.modules.workspace import crud as ws_crud
from app.modules.workspace.domain.visibility import effective_visibility_user_id
from app.core.config import get_settings
from app.services.k8s_client import K8sClient

logger = get_logger(__name__)

monitoring_router = APIRouter(tags=["monitoring"])


def get_k8s_client() -> K8sClient:
    return K8sClient(context=get_settings().kube_context or None)


def _matrix_values(prom_body: dict[str, Any]) -> list[list[Any]]:
    """从 Prom range_query 返回体取第一条 series 的 values (matrix)。

    avg()/max() 聚合掉所有标签 → 至多一条 series。无数据 (team 未占卡) → []。
    """
    result = ((prom_body or {}).get("data") or {}).get("result") or []
    if not result:
        return []
    return result[0].get("values") or []


@monitoring_router.get(
    "/workspaces/{ws_id}/gpu-utilization",
    response_model=GpuUtilizationResponse,
    summary="查询 ws 的 GPU 利用率时序",
    description=(
        "拉取该 ws 命名空间下 **过去 N 天** (`days` 1-30, 默认 7) 的 GPU 时序, 供 ws 概览页折线图使用. "
        "三条 series 各为 `[[unix_ts, \"value\"], ...]`:\n\n"
        "- `avg` / `max`: 该 ws 占用的 GPU 卡利用率% (0-100)\n"
        "- `count`: 当时占用的 GPU **卡数** (带该 namespace 标签的 DCGM series 数, 不是利用率)\n\n"
        "步长固定 **1h** (7d = 168 点). 某时刻没占卡 → 该点无数据, series 可能为空数组.\n\n"
        "**权限**: 仅 ws 管理员或平台超管可见 (个人隐私 · 2026-06-16).\n\n"
        "**数据源**: AWS Managed Prometheus (AMP), SigV4 签名. "
        "PromQL 走 `DCGM_FI_DEV_GPU_UTIL` (DCGM exporter), "
        "按 ws namespace 过滤后 `avg()` / `max()` / `count()` 聚合掉所有标签 → 每条至多一条 series."
    ),
    responses={
        403: {"description": "需要 workspace 管理员或平台超管"},
        404: {"description": "Workspace 不存在"},
        502: {"description": "AMP 不可用或 ws 未绑定 namespace"},
    },
)
async def workspace_gpu_utilization(
    ws_id: str,
    days: int = Query(default=7, ge=1, le=30),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> GpuUtilizationResponse:
    # 页面所有人可见, 但本图表仅 ws 管理员/超管可看 (2026-06-16)
    await assert_ws_admin(ws_id, current_user)

    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    namespace = ws.get("namespace") or (ws.get("metadata_json") or {}).get("namespace")
    if not namespace:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"workspace {ws_id} has no namespace"
        )

    queries = build_gpu_util_queries(namespace)
    window = gpu_util_time_window(days=days, now=time.time())
    try:
        avg_body = await prom_range_query(
            queries["avg"], window["start"], window["end"], window["step"]
        )
        max_body = await prom_range_query(
            queries["max"], window["start"], window["end"], window["step"]
        )
        count_body = await prom_range_query(
            queries["count"], window["start"], window["end"], window["step"]
        )
    except PromAPIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"prometheus http {exc.status_code}: {exc.body[:200]}",
        ) from exc

    return GpuUtilizationResponse(
        namespace=str(namespace),
        days=days,
        avg=_matrix_values(avg_body),
        max=_matrix_values(max_body),
        count=_matrix_values(count_body),
    )


# ===== Pure Prometheus passthrough =====


@monitoring_router.post(
    "/monitoring/query",
    response_model=PromResponse,
    summary="Prometheus instant query 透传",
    description=(
        "任意 PromQL 单点查询 (`/api/v1/query`) 透传, "
        "**服务端只做 SigV4 签名转发**, 不做 PromQL 改写.\n\n"
        "**权限**: 至少已登录 (不校验 ws 归属; 前端只在监控详情页调用, 未做敏感数据隔离).\n\n"
        "**数据源**: AWS Managed Prometheus (AMP)."
    ),
    responses={
        401: {"description": "未登录"},
        502: {"description": "AMP 返回非 2xx (PromQL 语法错误 / AMP 不可用)"},
    },
)
async def instant_query(
    payload: InstantQueryPayload,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> PromResponse:
    # 任意 PromQL passthrough: 至少要求已登录 (越权修复 2026-06-14)
    del current_user
    try:
        body = await prom_instant_query(payload.query, payload.time)
    except PromAPIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"prometheus http {exc.status_code}: {exc.body[:200]}",
        ) from exc
    return PromResponse(**body)


@monitoring_router.post(
    "/monitoring/query_range",
    response_model=PromResponse,
    summary="Prometheus range query 透传",
    description=(
        "任意 PromQL 区间查询 (`/api/v1/query_range`) 透传, "
        "服务端只做 SigV4 签名转发. 前端 echarts 折线图取此响应直接渲染 (Grafana 已弃用).\n\n"
        "**权限**: 至少已登录.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP)."
    ),
    responses={
        401: {"description": "未登录"},
        502: {"description": "AMP 返回非 2xx (PromQL 语法错误 / 时间窗过大 / AMP 不可用)"},
    },
)
async def range_query(
    payload: RangeQueryPayload,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> PromResponse:
    # 任意 PromQL passthrough: 至少要求已登录 (越权修复 2026-06-14)
    del current_user
    try:
        body = await prom_range_query(
            payload.query, payload.start, payload.end, payload.step
        )
    except PromAPIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"prometheus http {exc.status_code}: {exc.body[:200]}",
        ) from exc
    return PromResponse(**body)


# ===== Training job templates =====


@monitoring_router.get(
    "/training-jobs/{id}/monitoring/templates",
    response_model=list[QueryTemplate],
    summary="训练任务的 PromQL 模板",
    description=(
        "返回训练任务详情页监控 tab 的 PromQL 模板列表, 当前约 **180 个模板**, 按 `category` 分组:\n\n"
        "- `gpu` (~72): DCGM 全量 — 利用率 / 显存 / 温度 / 功耗 / SM 与 Tensor Core 活跃度 / 频率 / "
        "ECC 与 退役页 / 重映射 / XID / NVLink / PCIe / 限流违规\n"
        "- `efa` (~25): EFA 收发带宽 / 包率 / RDMA 读写 / 重传 / 丢包 / 错误\n"
        "- `status` (~14) + `event` (~8): Pod 阶段与就绪条件 / CrashLoop / ImagePullBackOff / OOMKilled / 退出码 / 重启\n"
        "- `memory` (~13) / `cpu` (~11) / `network` (~12) / `disk` (~9) / `process` (~5): cAdvisor 与 node 级资源\n"
        "- `training` (~11): 训练正常率 / 手动与自动重启 / 恢复开销 / Pod 成功失败数 / Operator 任务计数\n\n"
        "namespace / job label / pod regex / node regex 已替换实际值, 前端直接丢给 "
        "`/monitoring/query_range` 即可 (数量与分类以实际返回为准, 会随 promql 模板库增删).\n\n"
        "**权限**: 仅该 job 所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP), 指标来自 DCGM (`DCGM_FI_*`) + node exporter "
        "(`node_amazonefa_*` / node 级资源) + cAdvisor / kube-state (资源与 Pod 状态) + HyperPod Training Operator "
        "(`training_*` / operator 计数)."
    ),
    responses={
        403: {"description": "非该 job 所属 ws 的成员或超管"},
        404: {"description": "训练任务不存在"},
    },
)
async def training_templates(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await train_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    # 仅该 job 所属 ws 的成员或超管可看监控模板 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return await resolve_training_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_job_name=row.get("k8s_job_name") or row.get("k8s_name") or "",
    )


# ===== Dev instance templates =====


@monitoring_router.get(
    "/dev-instances/{id}/monitoring/templates",
    response_model=list[QueryTemplate],
    summary="开发实例的 PromQL 模板",
    description=(
        "返回开发实例监控 tab 的 PromQL 模板列表, 当前 **10 个**: "
        "GPU 利用率 / GPU 显存 / GPU 温度 / GPU 显存控制器繁忙 / CPU 使用量 / 内存使用 / "
        "磁盘读速率 / 磁盘写速率 / 网络入流量 / 网络出流量. "
        "namespace + pod regex (`workspace-<ws 名>-*`) + node regex 已替换实际值, "
        "前端丢给 `/monitoring/query_range` 渲染.\n\n"
        "**权限**: 仅该实例所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP); GPU 走 DCGM, CPU/内存 走 cAdvisor."
    ),
    responses={
        403: {"description": "非该实例所属 ws 的成员或超管"},
        404: {"description": "开发实例不存在"},
    },
)
async def dev_instance_templates(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await dev_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    # 仅该实例所属 ws 的成员或超管可看监控模板 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return await resolve_dev_instance_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_workspace_name=row.get("k8s_workspace_name") or row.get("k8s_name") or "",
    )


@monitoring_router.get(
    "/dev-instances/{id}/monitoring/kpi",
    response_model=list[QueryTemplate],
    summary="开发实例 KPI 卡片模板",
    description=(
        "开发实例详情页顶部 KPI 卡片使用的 PromQL 模板 (瞬时数字, 非时序), 当前固定 **3 张卡**:\n\n"
        "- `kpi_cpu_core_hours_30d` 累计 CPU 核小时 (过去 30d, `sum_over_time(...[30d:1h])`)\n"
        "- `kpi_gpu_mem_peak_gib` GPU 显存峰值 (过去 24h, GiB)\n"
        "- `kpi_idle_minutes` 闲置时长 (过去 1h 内 GPU util < 5% 的分钟数)\n\n"
        "前端配合 `/monitoring/query` (instant) 渲染.\n\n"
        "**权限**: 仅该实例所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP)."
    ),
    responses={
        403: {"description": "非该实例所属 ws 的成员或超管"},
        404: {"description": "开发实例不存在"},
    },
)
async def dev_instance_kpi(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await dev_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id}"
        )
    # 仅该实例所属 ws 的成员或超管可看 KPI (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return await resolve_dev_instance_kpi_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_workspace_name=row.get("k8s_workspace_name") or row.get("k8s_name") or "",
    )


# ===== Inference endpoint templates =====


@monitoring_router.get(
    "/inferences/{id}/monitoring/templates",
    response_model=list[QueryTemplate],
    summary="推理服务的 PromQL 模板 (SGLang)",
    description=(
        "推理服务详情页监控 tab 的 PromQL 模板列表, 当前约 **45 个模板**, 按 `category` 分组:\n\n"
        "- `sglang` (~29): 引擎业务指标 — QPS / TTFT 与 E2E 延迟 P50/P95/P99 / 队列等待 / 运行中请求 / "
        "生成与 prefill 吞吐 / KV cache 使用率与已用·可驱逐·空闲 tokens / prefix cache 命中率 / "
        "平均 prompt 与生成 token 数\n"
        "- `inference` (~8): IEC 前置 nginx / model 网关指标 — 调用速率 / 成功率 / TTFB p90 / 活跃连接 / 副本数\n"
        "- `gpu` (~4) / `cpu` / `memory` / `network` (~2): DCGM 与 cAdvisor 节点级资源\n\n"
        "namespace + pod regex (`<endpoint>-*`) + endpoint 名已替换实际值 "
        "(数量与分类以实际返回为准).\n\n"
        "**权限**: 仅该 endpoint 所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP); 引擎指标由 Inference Operator 的 OTel sidecar 抓 SGLang "
        "`/metrics` 后按 `resource_name=<endpoint>` 注入标签, 资源指标走 DCGM / cAdvisor 的 `pod` 过滤."
    ),
    responses={
        403: {"description": "非该 endpoint 所属 ws 的成员或超管"},
        404: {"description": "推理不存在"},
    },
)
async def inference_templates(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await inf_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"inference not found: {id}"
        )
    # 仅该 endpoint 所属 ws 的成员或超管可看监控模板 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return await resolve_inference_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_endpoint_name=row.get("k8s_endpoint_name") or "",
    )


# ===== Dynamo (多机推理) templates =====


@monitoring_router.get(
    "/dynamo-inferences/{id}/monitoring/templates",
    response_model=list[QueryTemplate],
    summary="Dynamo 多机推理的 PromQL 模板",
    include_in_schema=False,
    description=(
        "Dynamo (多机分布式推理) 详情页的 PromQL 模板列表, 约 **38 个**, 两部分:\n\n"
        "- **监控 tab** (~8): 复用 `INFERENCE_TEMPLATES` 里节点级 GPU / CPU / 内存 / 网络 (DCGM + cAdvisor), "
        "按 pod regex `<CR 名>-*` 覆盖 frontend + 所有 worker pod. "
        "SGLang 引擎与 nginx 网关那批被剔掉 (Dynamo 无对应 OTel 注入, 查了必空)\n"
        "- **引擎 tab** (30): `dynamo_*` 指标 — 请求速率 / 处理中请求 / 队列深度与容量 / KV cache 使用率与命中率 / "
        "TTFT 与 ITL P95 / 输入输出序列长度 / KV 传输与 tokenize 耗时 / Router 调度开销 / 模型上下文长度\n\n"
        "namespace + CR 名 + node regex 已替换实际值 (数量以实际返回为准).\n\n"
        "**权限**: 仅该 Dynamo 所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP); GPU 走 DCGM, 资源走 cAdvisor, "
        "`dynamo_*` 需 OTel 抓取管道就位后才出数."
    ),
    responses={
        403: {"description": "非该 Dynamo 所属 ws 的成员或超管"},
        404: {"description": "Dynamo 不存在"},
    },
)
async def dynamo_templates(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await dyn_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dynamo not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return await resolve_dynamo_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_cr_name=row.get("k8s_cr_name") or "",
    )


# ===== llm-d (LWS + sgl-model-gateway) templates =====


@monitoring_router.get(
    "/llmd-inferences/{id}/monitoring/templates",
    response_model=list[QueryTemplate],
    summary="llm-d 多机推理的 PromQL 模板 (节点级 + SGLang 引擎)",
    description=(
        "llm-d (分支B, LWS + sgl-model-gateway) 详情页监控 tab 的 PromQL 模板, 约 **37 个** — "
        "直接复用 `INFERENCE_TEMPLATES` 并剔掉 `category=inference` 那 8 个 "
        "(那批是 IEC 前置 nginx 的 `model_*` / `nginx_*`, llm-d 网关是 sgl-model-gateway 无 nginx, 查了必空):\n\n"
        "- SGLang 引擎业务指标 (~29): QPS / TTFT 与 E2E 延迟分位 / 队列等待 / KV cache 使用率与命中率 / 吞吐 / token 统计\n"
        "- 节点级 GPU / CPU / 内存 / 网络 (~8): DCGM + cAdvisor\n\n"
        "worker (`<name>-multi-*`) + gateway (`<name>-gateway-*`) 统一按 CR base 名前缀过滤; "
        "引擎指标按 `resource_name=<base 名>` 过滤 (数量以实际返回为准).\n\n"
        "**权限**: 仅该 llm-d 所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP); 引擎指标来自 OTel sidecar 抓 SGLang `/metrics` "
        "(worker 与 gateway 都静态注入 `resource_name`)."
    ),
    responses={
        403: {"description": "非该 llm-d 所属 ws 的成员或超管"},
        404: {"description": "llm-d 不存在"},
    },
)
async def llmd_templates(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await llmd_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"llmd not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    # base name (非 k8s_name=<name>-gateway): OTel resource_name + pod 前缀锚点
    return await resolve_llmd_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        k8s_name=row.get("name") or "",
    )


# ===== RayJob (KubeRay) templates =====


@monitoring_router.get(
    "/rayjobs/{id}/monitoring/templates",
    response_model=list[QueryTemplate],
    summary="RayJob 的 PromQL 模板 (节点级 + Ray 引擎)",
    include_in_schema=False,
    description=(
        "RayJob 详情页监控 tab 的 PromQL 模板. 节点级 GPU / 显存 / CPU / 内存 / 网络 "
        "(DCGM/cAdvisor, 覆盖 head+worker pod); Ray 引擎 ray_* 指标 (Observability "
        "add-on 采 Ray :8080). 按 RayCluster 名过滤.\n\n"
        "**权限**: 仅该 RayJob 所属 ws 的成员或超管.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP)."
    ),
    responses={
        403: {"description": "非该 RayJob 所属 ws 的成员或超管"},
        404: {"description": "RayJob 不存在"},
    },
)
async def rayjob_templates(
    id: str,  # noqa: A002
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[QueryTemplate]:
    row = await rayjob_crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    # ★ 用 ray_cluster_name (status.rayClusterName, sync 回填), 非 k8s_cr_name:
    # pod/AMP label = ray.io/cluster / ray_io_cluster = RayCluster 名。未 sync 时空 → 返 []。
    return await resolve_rayjob_templates(
        k8s,
        k8s_namespace=row.get("k8s_namespace") or "",
        ray_cluster_name=row.get("ray_cluster_name") or "",
    )


# ===== Kueue 队列 =====


@monitoring_router.get(
    "/monitoring/kueue-queues",
    response_model=list[KueueQueueRow],
    summary="各工作空间当前排队情况 (Kueue)",
    description=(
        "监控页「队列」表格: 每个可见 workspace 当前等待中的 workload 数.\n\n"
        "- `active`: 正常排队, 等前面跑完即可\n"
        "- `inadmissible`: 请求量超配额或拓扑不满足, 等下去也进不来, "
        "要改任务规格或加配额\n\n"
        "排序: 先 inadmissible 倒序 (要人处理的排前面), 再 active 倒序, 同数按 ws 名字稳定排序. "
        "每行的 `cluster_queue` = `<ws namespace>-clusterqueue`; **没有 namespace 的 ws 直接跳过** (建到一半的空壳).\n\n"
        "**权限**: 超管返回全部 ws; 普通用户仅自己 owner/member 的 ws.\n\n"
        "**数据源**: AWS Managed Prometheus (AMP) 一次 instant query `kueue_pending_workloads` "
        "(不带 cluster_queue 过滤, 取回全部队列 series 再在内存按 ws 归组), 指标由 Kueue controller 暴露. "
        "AMP 不可用时各项按 0 返回, 不报错."
    ),
    responses={401: {"description": "未登录"}},
)
async def kueue_queues(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[KueueQueueRow]:
    rows = await ws_crud.list_workspaces(
        None, user_id=effective_visibility_user_id(current_user)
    )
    return await list_kueue_queue_rows(rows)
