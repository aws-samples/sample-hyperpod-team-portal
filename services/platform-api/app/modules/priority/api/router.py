"""优先级管理 REST routes (WPC 档位 + 单任务优先级 + 抢占开关).

- 档位 (WPC) + 抢占开关: 仅平台超管 (require_admin)
- 改单任务优先级: 超管 OR ws 管理员 (assert_ws_admin; 任务总览页用, 普通成员只读)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.core.config import get_settings
from app.core.security import (
    assert_ws_admin,
    assert_ws_member,
    get_current_user,
    require_admin,
)
from app.modules.priority.api.schemas import (
    PreemptionSet,
    PreemptionState,
    PriorityClassCreate,
    PriorityClassItem,
    PriorityClassUpdate,
    WorkloadItem,
    WorkloadPriorityPatch,
)
from app.modules.priority.orchestration import service
from app.services.k8s_client import K8sClient

priority_router = APIRouter(tags=["priority"])


def get_k8s_client() -> K8sClient:
    return K8sClient(context=get_settings().kube_context or None)


# ---------- 档位 (WPC, 集群级, 仅超管) ----------

@priority_router.get(
    "/priority-classes",
    response_model=list[PriorityClassItem],
    summary="列优先级档 (集群级)",
    description=(
        "从 SageMaker ClusterSchedulerConfig (task governance) 读取集群优先级档位列表, "
        "按 value 降序返回. 用于任务创建 / 详情页的"
        "优先级下拉, 以及任务总览页把 DDB 里存的 priority_class_name 映射到数值 rank.\n\n"
        "**权限**: 所有登录用户可读; 建/改/删见其他接口 (仅超管).\n\n"
        "`description` 恒为 `null`, `in_use_count` 恒为 `0` (SageMaker 侧无这两项数据)."
    ),
    responses={
        401: {"description": "未登录"},
        400: {
            "description": "集群未配置 ClusterSchedulerConfig / hyperpod_cluster_name 为空"
        },
        502: {"description": "SageMaker API 调用失败"},
    },
)
async def list_priority_classes(
    k8s: K8sClient = Depends(get_k8s_client),
    _: dict[str, Any] = Depends(get_current_user),
) -> list[PriorityClassItem]:
    rows = await service.list_priority_classes(k8s)
    return [PriorityClassItem(**r) for r in rows]


@priority_router.post(
    "/priority-classes",
    response_model=PriorityClassItem,
    status_code=status.HTTP_201_CREATED,
    summary="新建优先级档 (同名则覆盖)",
    description=(
        "在 SageMaker 集群策略 (ClusterSchedulerConfig) 中创建优先级档位.\n\n"
        "`name` 为裸名 (例如 `high`), SageMaker 会生成对应 WPC 名 `<name>-priority`.\n"
        "`value` 为 SageMaker Weight, 范围 0–100, 越大越优先. `description` 字段不可写入"
        " (SageMaker 官方 API 无此入参, 响应里恒 `null`).\n\n"
        "**实为 upsert**: 同名档已存在时**静默覆盖其 Weight**, 仍返 201, 不报 409.\n\n"
        "**权限**: 仅平台超管 (require_admin)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        400: {
            "description": "集群未配置 ClusterSchedulerConfig / hyperpod_cluster_name 为空"
        },
        409: {
            "description": "写回时版本冲突 (TargetVersion 乐观锁) 或 config 非 SageMaker 托管"
        },
        422: {"description": "name / value 校验失败 (name 最长 40 字符, value 0–100)"},
        502: {"description": "SageMaker describe/update API 调用失败"},
    },
)
async def create_priority_class(
    payload: PriorityClassCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    _: dict[str, Any] = Depends(require_admin),
) -> PriorityClassItem:
    r = await service.create_priority_class(
        k8s, payload.name, payload.value, None
    )
    return PriorityClassItem(**r)


@priority_router.put(
    "/priority-classes/{name}",
    response_model=PriorityClassItem,
    summary="更新优先级档 value",
    description=(
        "更新 SageMaker 集群策略中指定档位的 Weight (`value`, 范围 0–100).\n"
        "`name` 可传裸名或带 `-priority` 全名, 后端会剥成裸名.\n\n"
        "`description` 字段不可写入 (SageMaker 官方 API 无此入参, 响应里恒 `null`).\n\n"
        "**同为 upsert**: `value` 给了就写回, 该档不存在时**直接创建**并返 200 "
        "(不会 404). 仅当 `value` 省略 (no-op 分支, 只回读当前值) 且档确实不存在时才 404.\n\n"
        "**不影响已存 Workload** — Workload 创建时把优先级数值 snapshot 到自身 spec, "
        "档位改后老任务的排位不动 (Kueue 语义).\n\n"
        "**权限**: 仅平台超管."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        400: {
            "description": "集群未配置 ClusterSchedulerConfig / hyperpod_cluster_name 为空"
        },
        404: {"description": "仅 `value` 省略时: 该 name 的优先级档不存在"},
        409: {
            "description": "写回时版本冲突 (TargetVersion 乐观锁) 或 config 非 SageMaker 托管"
        },
        422: {"description": "value 校验失败 (范围 0–100)"},
        502: {"description": "SageMaker describe/update API 调用失败"},
    },
)
async def update_priority_class(
    name: str,
    payload: PriorityClassUpdate,
    k8s: K8sClient = Depends(get_k8s_client),
    _: dict[str, Any] = Depends(require_admin),
) -> PriorityClassItem:
    r = await service.update_priority_class(
        k8s, name, payload.value, None
    )
    return PriorityClassItem(**r)


@priority_router.delete(
    "/priority-classes/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除优先级档",
    description=(
        "从 SageMaker 集群策略的 PriorityClasses 数组移除该档 "
        "(`name` 可传裸名或带 `-priority` 全名). 已引用该档的 Workload 依旧持有 "
        "snapshot value, 不会被回退.\n\n"
        "**权限**: 仅平台超管. **幂等**: 档不存在时仍原样写回一次, 返 204."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        400: {
            "description": "集群未配置 ClusterSchedulerConfig / hyperpod_cluster_name 为空"
        },
        409: {
            "description": "写回时版本冲突 (TargetVersion 乐观锁) 或 config 非 SageMaker 托管"
        },
        502: {"description": "SageMaker describe/update API 调用失败"},
    },
)
async def delete_priority_class(
    name: str,
    k8s: K8sClient = Depends(get_k8s_client),
    _: dict[str, Any] = Depends(require_admin),
) -> None:
    await service.delete_priority_class(k8s, name)


# ---------- 单任务优先级 (ws 成员; 任务总览页用) ----------

@priority_router.get(
    "/workspaces/{ws_id}/workloads",
    response_model=list[WorkloadItem],
    summary="列本 ws 的 Kueue Workload",
    description=(
        "**实时**列本 ws 下所有 Kueue Workload (跨 dev/训练/推理), 每行含任务名 / 状态 / 当前优先级档 / snapshot 数值. "
        "任务总览页配合 priority-classes 使用.\n\n"
        "**权限**: ws 成员或平台超管. 数据不落库, 每次现拉 K8s."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管"},
        404: {"description": "workspace 不存在 (仅超管可见此码, 非成员先被 403 拦)"},
        500: {"description": "K8s API 调用失败 (K8sAPIError 未被捕获)"},
    },
)
async def list_workloads(
    ws_id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[WorkloadItem]:
    # 仅 ws 成员或超管可列本 ws 的 Workload (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    rows = await service.list_workloads(k8s, ws_id)
    return [WorkloadItem(**r) for r in rows]


@priority_router.patch(
    "/workspaces/{ws_id}/tasks/{cr_name}/priority",
    summary="改单任务优先级",
    description=(
        "改**单个已在跑 / 排队任务**的优先级档:\n"
        "1. 按 `task_type + cr_name` 反查 Kueue Workload\n"
        "2. Patch 源 CR 的优先级 label\n"
        "3. 触发 Kueue 按新档重建 — **三类任务重建方式不同**:\n"
        "   - `train`: 删旧 Workload, Kueue 按 CR 新 label 重建 (无副作用)\n"
        "   - `dev` / `inference`: Workload 属于 Pod, 必须删 Deployment "
        "(`workspace-<cr_name>` / `<cr_name>`) 让 operator 重建 → "
        "**⚠️ 用户的开发机 / 推理容器会重启, 会话中断**\n\n"
        "`priority_class_name` 传 `GET /priority-classes` 返回的全名 (带 `-priority`).\n"
        "`task_type` 是裸 str 不做枚举校验; `dynamo` (多机推理) 明确不支持, 返 400.\n\n"
        "任务总览页的行内下拉调用. **权限**: ws 管理员或平台超管 (普通成员只读)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 管理员且非超管"},
        400: {
            "description": "task_type=dynamo (多机推理暂不支持调整优先级) / "
            "集群未配置 ClusterSchedulerConfig (校验目标档时)"
        },
        404: {
            "description": "workspace 不存在 / 未找到该任务对应的 Kueue Workload "
            "/ priority_class_name 对应的档不存在"
        },
        409: {"description": "任务已完成 (Workload Finished), 无法改优先级"},
        500: {"description": "K8s API 调用失败 (K8sAPIError 未被捕获)"},
        502: {"description": "校验目标档时 SageMaker API 调用失败"},
    },
)
async def patch_task_priority(
    ws_id: str,
    cr_name: str,
    payload: WorkloadPriorityPatch,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # 改单任务优先级: 仅 超管 OR 该 ws 管理员 (普通成员只读, 任务总览页入口同口径)
    await assert_ws_admin(ws_id, current_user)
    return await service.patch_task_priority(
        k8s, ws_id, payload.task_type, cr_name, payload.priority_class_name
    )


# ---------- 抢占开关 (ClusterQueue per-ws, 仅超管) ----------

@priority_router.get(
    "/workspaces/{ws_id}/preemption",
    response_model=PreemptionState,
    summary="查本 ws 抢占策略",
    description=(
        "读取本 ws 对应 ClusterQueue 的 `preemption.withinClusterQueue`, "
        "取值 `Never` / `LowerPriority` (决定高优任务能否踢掉低优任务, 释放算力). "
        "CR 上未设时按 `Never` 兜底返回. ClusterQueue 名按约定 `<namespace>-clusterqueue`.\n\n"
        "**权限**: ws 成员或平台超管."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管"},
        404: {"description": "workspace 不存在 (仅超管可见此码, 非成员先被 403 拦)"},
        500: {
            "description": "K8s API 调用失败 (含 ClusterQueue 不存在 — "
            "K8sAPIError 未被捕获)"
        },
    },
)
async def get_preemption(
    ws_id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> PreemptionState:
    # 仅 ws 成员或超管可查本 ws 抢占策略 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    return PreemptionState(**await service.get_preemption(k8s, ws_id))


@priority_router.put(
    "/workspaces/{ws_id}/preemption",
    response_model=PreemptionState,
    summary="设本 ws 抢占策略",
    description=(
        "改本 ws ClusterQueue 的 `preemption.withinClusterQueue`:\n"
        "- `Never`: 关闭抢占, 高优任务排队等资源\n"
        "- `LowerPriority`: 高优任务可踢掉本队列内低优在跑任务\n\n"
        "**权限**: 仅平台超管 (影响面大, 不给 ws admin)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
        404: {"description": "workspace 不存在"},
        422: {"description": "within_cluster_queue 值非法 (只接受 Never / LowerPriority)"},
        500: {
            "description": "K8s API 调用失败 (含 ClusterQueue 不存在 — "
            "K8sAPIError 未被捕获)"
        },
    },
)
async def set_preemption(
    ws_id: str,
    payload: PreemptionSet,
    k8s: K8sClient = Depends(get_k8s_client),
    _: dict[str, Any] = Depends(require_admin),
) -> PreemptionState:
    return PreemptionState(
        **await service.set_preemption(k8s, ws_id, payload.within_cluster_queue)
    )
