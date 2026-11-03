"""DevInstance 改规格编排 (DDB-only).

只改资源 (CPU/内存/GPU/EFA) 与资源池: merge-patch Workspace CR 的
spec.resources (+ 换池时 spec.affinity), 同步 DDB 业务字段。

不碰 spec.storage — 主存储 storage class 未开 allowVolumeExpansion, EBS 不能扩;
只 patch resources/affinity → PVC (workspace-<name>-pvc) 引用不动, operator 滚新
Pod 复用同块 EBS → /home/sagemaker-user 数据保留。运行中改会重建 Pod (中断当前会话), 由前端提示。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import HTTPException, status

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.i18n import t
from app.core.logging import get_logger

from app.modules.workspace import crud as ws_crud

from ..api.schemas import DevInstanceResize
from ..domain.cr import build_affinity, build_resources, build_security_context, build_volumes
from ..persistence import crud
from .create import _resolve_cpu_instance_groups
from .lifecycle import _assert_is_creator, _get_or_404, audit_devinstance
from .mounts import resolve_mounts

logger = get_logger(__name__)


async def resize_flow(
    db: Any,
    k8s: K8sClient,
    hp: Any,
    id_: Any,
    payload: DevInstanceResize,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del db
    row = await _get_or_404(None, id_)
    await _assert_is_creator(row, user)

    ws_id = str(row.get("workspace_id") or "")

    # 资源池不可改: 换池 (CPU↔GPU) 必然与镜像错配 — 镜像不在 resize 范围内 (spec.image
    # 不动), CPU 镜像落 GPU 节点则 GPU 挂上也无 CUDA 用不了, 反之则浪费。前端已把资源池
    # 置只读, 但 agent 可能直接调本 API, 故后端硬拦: 传入 pool 与当前池不一致直接 400。
    # 当前池取 metadata.pool, 缺失则按 gpu_count 派生。省略 pool (None) = 不动机型约束。
    current_pool = (row.get("metadata_json") or {}).get("pool") or (
        "gpu" if int(row.get("gpu_count") or 0) > 0 else "cpu"
    )
    if payload.pool and payload.pool != current_pool:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t("devinstance.pool_immutable"),
        )

    # 同池内改资源 (payload.pool 非空且 == current_pool): 展开该池机型重算 nodeAffinity。
    # 复用创建流同一函数 (后端 EC2 GpuInfo 权威判池), 空 → 400 (该池无可用机型)。
    # CPU 池 (gpu_count==0) 额外算软优先 CPU instance group。
    # pool=None → 不动 affinity (只改资源, 保留原机型约束)。
    resources = build_resources(
        cpu_millicores=payload.cpu_request_millicores,
        memory_mib=payload.memory_request_mib,
        gpu_count=payload.gpu_count,
        efa_count=payload.efa_count,
    )
    # merge-patch (RFC 7386) 递归合并, 不写的 key 保留旧值 — 只有显式 null 才删。
    # build_resources 只在 >0 时写扩展资源, GPU→CPU 降级时这些 key 缺席, 旧的
    # nvidia.com/gpu / efa 会被留在 CR 里 (resources 仍要 GPU 但 affinity 已换 CPU
    # → Kueue 永远调度不上)。这里对降到 0 的扩展资源显式补 null 强制删除。
    for ext_key, count in (
        ("nvidia.com/gpu", payload.gpu_count),
        ("vpc.amazonaws.com/efa", payload.efa_count),
    ):
        if count <= 0:
            resources["requests"][ext_key] = None
            resources["limits"][ext_key] = None
    patch_spec: dict[str, Any] = {"resources": resources}
    if payload.pool:
        from app.modules.quota.orchestration.workspace_quota import (
            list_workspace_pool_instance_types,
        )

        pool_instance_types = await list_workspace_pool_instance_types(
            None, hp, ws_id, payload.pool
        )
        if not pool_instance_types:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                t("devinstance.pool_no_instance_types", pool=payload.pool),
            )
        preferred_igs: list[str] = []
        if not payload.gpu_count:
            preferred_igs = await _resolve_cpu_instance_groups()
        patch_spec["affinity"] = build_affinity(
            instance_types=pool_instance_types,
            preferred_instance_groups=preferred_igs,
        )

    # 挂载编辑 (可选): payload.volume_mounts is None → 不碰挂载 (向后兼容, agent 只改资源);
    # 给出列表 (含 []) → 全量替换成恰好这些挂载。走与创建同一 resolve_mounts (授权 +
    # PVC 存在校验 + gid), 保证判定不分叉; 前端弹窗预填当前挂载后整表下发, 所见即所得。
    volume_mounts_json: list[dict[str, Any]] | None = None
    if payload.volume_mounts is not None:
        ws = await ws_crud.get_workspace(None, ws_id)
        ws_md = (ws or {}).get("metadata_json") or {}
        username = str((user or {}).get("username") or (user or {}).get("user_id") or "")
        volume_mounts_json, primary_gid, supplemental_gids = await resolve_mounts(
            k8s,
            ws_id=ws_id,
            k8s_ns=row["k8s_namespace"],
            username=username,
            ws_md=ws_md,
            volume_mounts=payload.volume_mounts,
        )
        # merge-patch 数组整体覆盖: 传全量 (含 []) 即设为恰好这些 → 支持清空。
        patch_spec["volumes"] = build_volumes(volume_mounts_json)
        # securityContext: 有 primary_gid 则按重算的 gid 下发; 无 (清空挂载且 ws 无
        # primary_gid) 则显式 null 删除旧字段, 回落 template default fsGroup 1000。
        sc = build_security_context(primary_gid, supplemental_gids)
        if sc:
            patch_spec.update(sc)
        else:
            patch_spec["containerSecurityContext"] = None
            patch_spec["podSecurityContext"] = None

    try:
        await k8s.patch_workspace(
            row["k8s_namespace"],
            row["k8s_workspace_name"],
            {"spec": patch_spec},
        )
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s patch failed: {exc.message}",
        ) from exc

    # 同步 DDB 业务字段 (资源真值 + metadata.pool)。crud.update 从 row 取
    # _DEV_BUSINESS_FIELDS, 直接改 row 再落库。
    row["cpu_request_millicores"] = payload.cpu_request_millicores
    row["memory_request_mib"] = payload.memory_request_mib
    row["gpu_count"] = payload.gpu_count
    row["efa_count"] = payload.efa_count
    if payload.pool or volume_mounts_json is not None:
        md = dict(row.get("metadata_json") or {})
        if payload.pool:
            md["pool"] = payload.pool
        if volume_mounts_json is not None:
            md["volume_mounts"] = volume_mounts_json
        row["metadata_json"] = md
    await crud.update(None, row)

    await audit_devinstance(row, user, "devinstance.resize")
    logger.info(
        "dev_instance.resize.ok",
        id=str(row.get("id")),
        cpu=payload.cpu_request_millicores,
        mem=payload.memory_request_mib,
        gpu=payload.gpu_count,
        efa=payload.efa_count,
        pool=payload.pool,
    )

    # 运行中改规格: operator 不会因 spec.resources/affinity 变更自动滚 Deployment
    # (实测只 patch 资源不生效, Deployment 仍是旧 spec), 必须 stop→start 让 operator
    # 按新 spec 重建 Deployment。停机态 (desiredStatus 已 Stopped) 无需重建 —— 下次
    # start 自然读新 spec。连接走 directSSH: pod 重起后 add-on 重建 ssh-<name>
    # Service, external-dns 同步同一固定 DNS (停启不变), 平台无需做任何注册。
    if str(row.get("desired_status") or "").lower() == "running":
        _schedule_rebuild(k8s, row)

    return row


# 防止 fire-and-forget asyncio.create_task 被 GC 吞掉异常的 strong-ref set
_BG_TASKS: set["asyncio.Task[Any]"] = set()


def _schedule_rebuild(k8s: K8sClient, row: dict[str, Any]) -> None:
    """后台触发 stop→start 重建, 不阻塞改规格响应 (fire-and-forget)。"""
    bg = asyncio.create_task(_rebuild_for_resize(k8s, dict(row)))
    _BG_TASKS.add(bg)
    bg.add_done_callback(_BG_TASKS.discard)


async def _rebuild_for_resize(k8s: K8sClient, instance: dict[str, Any]) -> None:
    """stop → 等 operator 真停 → start, 让 operator 按新 spec 重建 Deployment。

    两次 patch 之间必须等 Stopped 生效: 否则 Stopped/Running 被 operator 合并成
    "没变化", Deployment 不会重建。等不到就超时后仍尝试 start, 避免卡在 Stopped。
    """
    ns = instance["k8s_namespace"]
    name = instance["k8s_workspace_name"]
    inst_id = str(instance.get("id") or "")
    try:
        await k8s.patch_workspace(ns, name, {"spec": {"desiredStatus": "Stopped"}})
    except Exception as exc:  # noqa: BLE001 - 后台任务不能抛
        logger.warning("resize.rebuild.stop_fail", id=inst_id, err=str(exc))
        return

    stopped = await _wait_stopped(k8s, ns, name)
    if not stopped:
        logger.warning("resize.rebuild.stop_timeout", id=inst_id)

    try:
        await k8s.patch_workspace(ns, name, {"spec": {"desiredStatus": "Running"}})
        logger.info("resize.rebuild.restarted", id=inst_id, waited_stopped=stopped)
    except Exception as exc:  # noqa: BLE001
        logger.warning("resize.rebuild.start_fail", id=inst_id, err=str(exc))


async def _wait_stopped(
    k8s: K8sClient,
    namespace: str,
    name: str,
    timeout_sec: float = 120.0,
    interval_sec: float = 3.0,
) -> bool:
    """轮询 Workspace status.conditions, 等 Stopped==True (operator 已把 pod 拆完)。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            ws = await k8s.get_workspace(namespace, name)
        except Exception:  # noqa: BLE001 - 读失败当作还没停, 继续等
            await asyncio.sleep(interval_sec)
            continue
        conds = (ws.get("status") or {}).get("conditions") or []
        if any(
            c.get("type") == "Stopped" and str(c.get("status")) == "True"
            for c in conds
        ):
            return True
        await asyncio.sleep(interval_sec)
    return False
