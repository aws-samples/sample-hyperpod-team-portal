"""任务总览路由 (只读总览)。

改优先级 / 列优先级档 复用 priority 模块 (app/modules/priority): 已实现
PriorityMixin (含 patch CR label + delete Workload 重建, 真集群实测正确)。本模块
只保留总览页 + can_edit_priority (控制前端入口显隐)。

总览恒只显示活跃任务 (active_only=True)。每行补 priority_value: 调一次 K8s
list_priority_classes 拿 名字→数值 映射, 供前端按优先级数值排序 (DDB 只存名字)。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.security import assert_ws_admin, get_current_user
from app.modules.priority.orchestration import service as priority_service
from app.modules.tasks import service
from app.services.k8s_client import K8sClient

from .schemas import TaskOverviewResponse

logger = logging.getLogger("platform_api.tasks")

tasks_router = APIRouter(tags=["tasks"])


def get_k8s_client() -> K8sClient:
    return K8sClient(context=get_settings().kube_context or None)


async def get_priority_class_values(
    k8s: K8sClient = Depends(get_k8s_client),
) -> dict[str, int]:
    """WPC 名字→数值 rank 映射 (供任务总览给每行补 priority_value)。

    单独抽成依赖, 测试可 override 不连真集群。K8s 不可达时退化为空映射
    (priority_value 全 None, 前端优先级排序退化为按时间排, 不阻塞总览)。
    """
    try:
        rows = await priority_service.list_priority_classes(k8s)
    except Exception:
        # K8s 不可达 / 返回异常 → 退化空映射, 但记日志 (否则 "优先级全 None"
        # 与真实集群无优先级档无法区分, 运维看不到 K8s 故障)。
        logger.warning("list_priority_classes failed; priority_value 退化为空映射", exc_info=True)
        return {}
    return {r["name"]: r["value"] for r in rows if r.get("name") is not None}


@tasks_router.get(
    "/workspaces/{ws_id}/tasks",
    response_model=TaskOverviewResponse,
    summary="任务总览 (跨类型只读)",
    description=(
        "本 ws 全部**活跃**任务的统一总览 (跨 dev / train / inference / dynamo / llmd), 用于任务总览页表格.\n\n"
        "- `active_only=True` 恒定: 走一次 DDB 稀疏 GSI (active-index) 聚合读, 其余全内存算\n"
        "- **另打一次 K8s**: `list_priority_classes` 拿 WPC name → 数值 rank 映射, 给每行补 "
        "`priority_value` 供前端按优先级排序 (DDB 只存名字)\n"
        "- K8s 不可达时该映射退化为空, `priority_value` 全 None (排序退化为按创建时间), 不阻塞总览\n"
        "- 排序: 优先级降序 → 同优先级内 `created_at` 升序 (FIFO); `priority_value` 为 None 沉底\n"
        "- 返回还含 `can_edit_priority` (是否 ws 管理员, 控制前端改优先级入口显隐) "
        "与 `stats` (running_starting / queued 两桶计数)\n"
        "- 上游 DDB 查询 limit=200, 单 ws 任务超 200 会被截断 (M1 阶段够用)\n\n"
        "**权限**: 2026-06-15 起收紧为 ws 管理员或平台超管 (总览页仅供调优先级使用). "
        "ws 不存在时按 **403** 返 (不查 ws 是否存在)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 管理员且非超管 (含 ws 不存在)"},
    },
)
async def get_task_overview(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    priority_values: dict[str, int] = Depends(get_priority_class_values),
) -> TaskOverviewResponse:
    # 任务总览仅为调优先级而设, 普通成员不能调优先级 → 仅 ws 管理员或平台超管可看
    # (2026-06-15: 从 assert_ws_member 收紧为 assert_ws_admin)
    await assert_ws_admin(ws_id, current_user)
    data = await service.build_overview(
        ws_id,
        current_user=current_user,
        active_only=True,
        priority_values=priority_values,
    )
    return TaskOverviewResponse(**data)


@tasks_router.get(
    "/workspaces/{ws_id}/tasks/queue-order",
    response_model=dict[str, dict[str, Any]],
    summary="排队任务的 Kueue 队列位置",
    description=(
        "**实时**拉 Kueue LocalQueue (`<ns>-localqueue`) 的 pendingworkloads, 返 "
        "`{cr_name: {position(min), workloads:[{name, position, priority}]}}` 映射, "
        "供任务总览页给排队中 (Pending) 的行显示 排位 x/n.\n\n"
        "- 只包含还在排队的 Workload; 已 Admitted / Finished 的不在返回里\n"
        "- 不落库, 每次现拉 K8s; 按 Workload `ownerReferences[0]` 归一回任务 CR 名\n"
        "- 一任务多 Workload (dynamo 多 Pod / llm-d 多组件 / 推理多副本) 聚合取 min 作主 "
        "`position`, 明细全给前端\n"
        "- **降级不报错**: Kueue 不可达 / LocalQueue 不存在 / 任何异常 → 返回空映射 `{}` "
        "(静默降级, 不阻塞总览)\n\n"
        "**权限**: ws 管理员或平台超管. ws 不存在时按 **403** 返."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 管理员且非超管 (含 ws 不存在)"},
    },
)
async def get_task_queue_order(
    ws_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    k8s: K8sClient = Depends(get_k8s_client),
) -> dict[str, dict[str, Any]]:
    await assert_ws_admin(ws_id, current_user)
    return await service.get_queue_order(ws_id, k8s)
