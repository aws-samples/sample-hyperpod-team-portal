"""DevInstance 生命周期编排 (DDB-only)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.adapters.ddb import tables as _tables
from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.i18n import t
from app.core.logging import get_logger
from app.repositories import resource_index as ri_repo

from ..api.schemas import DevInstanceUpdate
from ..persistence import crud

logger = get_logger(__name__)

_SSM_REGISTRATION_PATH = "/var/lib/amazon/ssm/registration"
_SSM_CONTAINER = "ssm-agent-sidecar"
_WORKSPACE_CONTAINER = "workspace"


async def sync_from_k8s(
    db: Any,
    k8s: K8sClient,
    instance: dict[str, Any],
    *,
    persist: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """§7.2 解析 status.conditions → phase. 失败不阻塞.

    persist=False 时不写 DDB · 列表场景 (N 行高频读) 用, 避免每次 list 都触发
    N 次 DDB write + GSI 更新. 详情/lifecycle 操作仍 persist=True 保证状态落库.
    """
    del db
    conditions: list[dict[str, Any]] = []
    try:
        ws_cr = await k8s.get_workspace(
            instance["k8s_namespace"], instance["k8s_workspace_name"]
        )
    except K8sAPIError as exc:
        if "404" in exc.code:
            instance["phase"] = "Terminating"
            instance["last_sync_at"] = datetime.now(UTC).isoformat()
            if persist:
                await crud.update(None, instance)
            return instance, []
        logger.info(
            "dev_instance.sync.k8s_err",
            id=str(instance.get("id")),
            code=exc.code,
            msg=exc.message,
        )
        return instance, []

    conditions = (ws_cr.get("status") or {}).get("conditions") or []

    # phase 原始值: 所有 status==True 的 condition type 用 "/" 拼接 (与 informer 同源)。
    # 不再归一 (去 derive_devinstance_phase + 去"主容器 ready 提成 Running"兜底):
    # 运行中原始 phase = 含 "Available"; 就绪兜底场景由代理 gate 负向放行 + pod-IP 检查把守。
    true_conds = [c for c in conditions if c.get("status") == "True"]
    phase = "/".join(c.get("type") for c in true_conds if c.get("type"))
    by_type = {c.get("type"): c for c in conditions}
    started = (by_type.get("Available") or {}).get("lastTransitionTime")

    # kueue_status (生命周期三态 queued/started/finished) 现由 informer 写
    # (derive_dev_kueue_status), sync 不再计算 — 见 KS-1~6。

    instance["phase"] = phase
    if "Stopped" in phase:
        instance["ssm_managed_id"] = None
        instance["started_at"] = None
    elif "Available" in phase and not instance.get("started_at"):
        instance["started_at"] = started or datetime.now(UTC).isoformat()

    instance["access_url"] = (ws_cr.get("status") or {}).get("accessURL")

    latest = conditions[-1] if conditions else {}
    instance["last_condition_message"] = latest.get("message")
    instance["last_sync_at"] = datetime.now(UTC).isoformat()

    if "Available" in instance["phase"] and not instance.get("ssm_managed_id"):
        try:
            ssm_id = await _extract_ssm_id(k8s, instance)
            if ssm_id:
                instance["ssm_managed_id"] = ssm_id
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "dev_instance.sync.ssm_extract_fail",
                id=str(instance.get("id")),
                err=str(exc),
            )

    if persist:
        await crud.update(None, instance)
    return instance, conditions


async def _extract_ssm_id(
    k8s: K8sClient, instance: dict[str, Any]
) -> str | None:
    pod = await k8s.get_pod_by_workspace(
        instance["k8s_namespace"], instance["k8s_workspace_name"]
    )
    if not pod:
        return None
    pod_name = (pod.get("metadata") or {}).get("name")
    if not pod_name:
        return None
    raw = await k8s.read_pod_file(
        namespace=instance["k8s_namespace"],
        pod_name=pod_name,
        container=_SSM_CONTAINER,
        path=_SSM_REGISTRATION_PATH,
    )
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            mid = data.get("ManagedInstanceID") or data.get(
                "managedInstanceID"
            )
            if mid:
                return mid
    except json.JSONDecodeError:
        pass
    m = re.search(r"(mi-[0-9a-f]{8,})", raw)
    return m.group(1) if m else None


async def stop_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    try:
        await k8s.patch_workspace(
            row["k8s_namespace"],
            row["k8s_workspace_name"],
            {"spec": {"desiredStatus": "Stopped"}},
        )
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s patch failed: {exc.message}",
        ) from exc

    # directSSH: 无 SSM mi 需注销 (连接靠固定 DNS)。老数据可能残留 mi, 顺手清掉。
    old_mi = row.get("ssm_managed_id")
    if old_mi:
        from app.adapters.aws.ssm import deregister_managed_instance
        await deregister_managed_instance(old_mi)

    row["desired_status"] = "Stopped"
    row["stopped_at"] = datetime.now(UTC).isoformat()
    row["ssm_managed_id"] = None
    row["started_at"] = None
    await crud.update(None, row)
    await audit_devinstance(row, user, "devinstance.stop")
    return row


async def start_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> dict[str, Any]:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    try:
        await k8s.patch_workspace(
            row["k8s_namespace"],
            row["k8s_workspace_name"],
            {"spec": {"desiredStatus": "Running"}},
        )
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s patch failed: {exc.message}",
        ) from exc
    row["desired_status"] = "Running"
    await crud.update(None, row)
    await audit_devinstance(row, user, "devinstance.start")

    # directSSH: pod 重新起来后 addon 自动重建 ssh-<name> Service + external-dns
    # 同步 DNS, 固定 DNS 名停启不变, 平台无需做任何注册。
    return row


# 防止 fire-and-forget asyncio.create_task 被 GC 吞掉异常的 strong-ref set
_BG_TASKS: set["asyncio.Task[Any]"] = set()


async def _post_start_ssm_init(
    k8s: K8sClient, instance: dict[str, Any]
) -> None:
    """Stop→Start 后重跑 SSM 注册 (老 mi 失效, sidecar 新 Pod 重启 ssm-agent).

    跟 create.py:_post_create_ssm_init 行为一样, 但拷过来避免循环 import.
    """
    from .ssm_register import register_ssm_in_sidecar

    inst_id = str(instance.get("id") or "")
    try:
        await crud.update(
            None, {**instance, "ssm_init_status": "registering"}
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("ssm_init.start.mark_fail", id=inst_id, err=str(exc))

    try:
        mi = await register_ssm_in_sidecar(k8s, instance)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ssm_init.start.unexpected", id=inst_id, err=str(exc))
        mi = None

    try:
        latest = await crud.get(None, inst_id) or instance
    except Exception:  # noqa: BLE001
        latest = instance

    if mi:
        latest["ssm_managed_id"] = mi
        latest["ssm_init_status"] = "done"
    else:
        latest["ssm_init_status"] = "failed"

    try:
        await crud.update(None, latest)
        logger.info(
            "ssm_init.start.complete",
            id=inst_id,
            mi=mi,
            status=latest["ssm_init_status"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ssm_init.start.write_fail", id=inst_id, err=str(exc))


# 创建期 SSM 注册的"事后兜底": 创建流的后台任务 (_post_create_ssm_init) 是
# 一次性的 —— 若创建初期因资源紧张, sidecar 在 _wait_sidecar_present 的 600s 窗口
# 内一直没 running, 注册任务就超时放弃, 之后不再重试, 开发机永远卡在 Progressing
# (边车 not-ready)。这里在"用户打开详情页"时做一次补偿: 若开发机已卡够久且
# sidecar 现在确实 running 了 (资源后来够了), 就再触发一次注册。
_SSM_RECOVER_MIN_AGE_SEC = 15 * 60  # 创建满 15min 才补 (与后端注册全链路最坏耗时


async def maybe_recover_ssm(k8s: K8sClient, instance: dict[str, Any]) -> None:
    """详情页读取时的 SSM 注册兜底 (fire-and-forget, 不阻塞响应)。

    仅在以下条件**全满足**时, 后台触发一次 register_ssm_in_sidecar:
      - phase 卡在"启动中"(非 Available / 非 Stopped / 非 Terminating)
      - 创建已超过 15 分钟 (创建流那次 600s 窗口早已结束, 无并发)
      - ssm_init_status 非 registering (registering 表示已有任务在跑, 不重入)
      - 容器级精准判据 (_ssm_recoverable_by_pod): 主容器已 ready 且 sidecar running
        但 not-ready —— 即"资源已就位、容器已起、纯差 SSM 注册"。这把真正的注册
        问题与"资源不足/拉镜像慢"(主容器都没 ready) 区分开, 后者直接跳过不触发。

    注意: 不能凭 DDB 的 ssm_init_status=done / 有 ssm_managed_id 就跳过 —— pod 重建
    (stop→start / 崩溃重启) 后, DDB 还留着上次注册的 done+旧 mi, 但新 pod 边车并未
    重新注册。此时应以 pod 真实状态 (_ssm_recoverable_by_pod) 为准判断是否补注册。
    """
    phase = str(instance.get("phase") or "")
    if "Available" in phase or "Stopped" in phase or "Terminating" in phase:
        return
    # 只挡 registering (已有注册任务在跑, 防并发); done/有 mi 不再硬跳过 —— 由下方
    # 容器级判据看当前 pod 边车是否真 ready 决定, 覆盖 pod 重建后 DDB 状态过期的情况。
    if instance.get("ssm_init_status") == "registering":
        return

    created_at = instance.get("created_at")
    if not created_at:
        return
    try:
        created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return
    age_sec = (datetime.now(UTC) - created_dt).total_seconds()
    if age_sec < _SSM_RECOVER_MIN_AGE_SEC:
        return

    # 精准判据: 只有"主容器已 ready 且 sidecar 容器 running 但 not-ready"才补注册。
    # 这能把"卡 Progressing"里真正的 SSM 注册问题, 和"资源不足/拉镜像慢"区分开:
    #   - 资源不足/拉镜像中 → 主容器没 ready (甚至容器没起) → 不触发 (避免空等 600s)
    #   - 纯差 SSM 注册     → 主容器 ready + sidecar running 卡 not-ready → 触发
    inst_id = str(instance.get("id") or "")
    try:
        recoverable = await _ssm_recoverable_by_pod(k8s, instance)
    except Exception as exc:  # noqa: BLE001
        logger.info("ssm_recover.pod_check_skip", id=inst_id, err=str(exc))
        return
    if not recoverable:
        return

    import asyncio

    logger.info("ssm_recover.trigger", id=inst_id, phase=phase, age_sec=int(age_sec))
    # 复用 _post_start_ssm_init: 它会标 registering → 调 register → 写回 mi/状态。
    # registering 标记同时挡住后续详情请求重复触发 (上面的 registering 过滤)。
    _bg = asyncio.create_task(_post_start_ssm_init(k8s, instance))
    _BG_TASKS.add(_bg)
    _bg.add_done_callback(_BG_TASKS.discard)


async def ssm_recovery_sweep(interval_sec: int = 900) -> None:
    """后台周期扫描: 对所有 ws 卡 Progressing 的开发机补 SSM 注册 (默认 15 分钟一轮)。

    访问驱动的补偿 (list/detail 触发) 只在有人看页面时跑; 本 sweep 兜住"pod 重建后
    无人访问 → 永远卡 Progressing"的洞。由 main.py lifespan 起后台任务。

    多副本安全: maybe_recover_ssm 靠 registering 标记 + register 幂等防重, 无需 leader 锁。
    维护: 每轮 list 所有 ws → list 各 ws 开发机 → maybe_recover_ssm (仅对边车 not-ready
    的真正触发)。单轮异常不中断循环; 收到 CancelledError (关闭) 正常退出。
    """
    import asyncio

    from app.adapters.k8s import K8sClient
    from app.core.config import get_settings
    from app.modules.workspace.persistence import crud as ws_crud
    from . import crud as dev_crud

    while True:
        try:
            await asyncio.sleep(interval_sec)  # 先睡, 避开启动峰值
            k8s = K8sClient(context=get_settings().kube_context or None)
            workspaces = await ws_crud.list_workspaces(None)
            n_scan = 0
            for ws in workspaces:
                ws_id = str(ws.get("workspace_id") or ws.get("id") or "")
                if not ws_id:
                    continue
                rows = await dev_crud.list_by_workspace(None, ws_id)
                for row in rows:
                    n_scan += 1
                    # maybe_recover_ssm 内部再筛 (Progressing + 15min + 边车 not-ready),
                    # 只对真卡住的触发补注册; 其余瞬间跳过。
                    await maybe_recover_ssm(k8s, row)
            logger.info("ssm_sweep.done", scanned=n_scan, ws=len(workspaces))
        except asyncio.CancelledError:
            logger.info("ssm_sweep.cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - 单轮出错不能让循环死掉
            logger.warning("ssm_sweep.error", err=str(exc))


def schedule_ssm_recovery(k8s: K8sClient, rows: list[dict[str, Any]]) -> None:
    """列表页用: 对一批开发机后台跑 SSM 注册兜底 (fire-and-forget, 不阻塞列表响应)。

    每行先走 maybe_recover_ssm 的纯 DDB 预筛 (phase/mi/ssm_init_status/创建时间),
    绝大多数行瞬间排除、零 K8s 调用; 仅"疑似卡住"的极少数行才查 pod。整体丢后台,
    列表响应不等。registering 标记防重入 (30s 轮询 + 多副本不会重复触发)。
    """
    import asyncio

    async def _run() -> None:
        for r in rows:
            try:
                await maybe_recover_ssm(k8s, r)
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "ssm_recover.list_skip", id=str(r.get("id")), err=str(exc)
                )

    _bg = asyncio.create_task(_run())
    _BG_TASKS.add(_bg)
    _bg.add_done_callback(_BG_TASKS.discard)


def _container_ready(statuses: list[dict[str, Any]], name: str) -> tuple[bool, bool]:
    """返 (running, ready): 该容器是否 running、是否 ready。找不到返 (False, False)。

    pod dict 经 to_dict() 是 snake_case (container_statuses), 但保留 camelCase
    兜底 (与 ssm_register._wait_sidecar_present 同口径)。
    """
    for cs in statuses:
        if cs.get("name") != name:
            continue
        running = (cs.get("state") or {}).get("running") is not None
        return running, bool(cs.get("ready"))
    return False, False


async def _ssm_recoverable_by_pod(
    k8s: K8sClient, instance: dict[str, Any]
) -> bool:
    """查 pod 容器级状态, 判断"是不是纯差 SSM 注册"(可补) 还是"资源/镜像问题"(不补)。

    可补 = 主容器 (workspace) 已 ready 且 sidecar 容器 running 但 not-ready。
      - 主容器没 ready / 容器没起 → 资源不足或拉镜像中, 注册补了也没用 (sidecar 还没 running)
      - sidecar 已 ready → 其实已经注册好了 (理论不该进到这), 不补
    """
    pod = await k8s.get_pod_by_workspace(
        instance["k8s_namespace"], instance["k8s_workspace_name"]
    )
    if not pod:
        return False
    status_ = pod.get("status") or {}
    statuses = (
        status_.get("container_statuses")
        or status_.get("containerStatuses")
        or []
    )
    _, main_ready = _container_ready(statuses, _WORKSPACE_CONTAINER)
    sc_running, sc_ready = _container_ready(statuses, _SSM_CONTAINER)
    return main_ready and sc_running and not sc_ready


async def delete_flow(
    db: Any, k8s: K8sClient, id_: Any, user: dict[str, Any] | None = None
) -> None:
    del db
    row = await _get_or_404(None, id_)
    await _assert_can_operate(row, user)
    try:
        await k8s.delete_workspace(
            row["k8s_namespace"], row["k8s_workspace_name"]
        )
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"k8s delete failed: {exc.message}",
        ) from exc

    # 顺手清 SSM managed instance 条目 (mi-xxx) · 防累积占 advanced tier 配额.
    # K8s 删 Workspace → spaces operator 销毁 Pod → sidecar 容器消失, 但
    # SSM service-side mi-xxx 注册条目仍在 (PingStatus 变 ConnectionLost).
    # 不主动清, mi-xxx 累积没人收 → SSM 配额耗尽 / Console 一堆历史脏数据.
    mi = row.get("ssm_managed_id")
    if mi:
        from app.adapters.aws.ssm import deregister_managed_instance
        await deregister_managed_instance(mi)

    # 软删 DDB 行 (打 deleted_at), 不硬删 — 列表过滤, 审计可查; informer 收 DELETED
    # 再 mark_deleted 幂等。此处先打标避免 worker 没跑时孤儿行。(照训练范本)
    await ri_repo.mark_deleted(
        row["workspace_id"], _tables.RESOURCE_TYPE_DEV, row["id"]
    )
    # 级联清分享记录 (best-effort, 失败不阻塞删除)。
    try:
        from app.repositories import resource_shares as shares_repo
        await shares_repo.delete_by_resource(
            row["workspace_id"], _tables.RESOURCE_TYPE_DEV, row["id"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dev_instance.delete.share_cleanup_fail",
            id=str(id_), err=str(exc),
        )
    logger.info(
        "dev_instance.delete.ok",
        id=str(id_),
        k8s_name=row["k8s_workspace_name"],
        mi=mi,
    )
    await audit_devinstance(row, user, "devinstance.delete")


async def update_flow(
    db: Any, k8s: K8sClient, id_: Any, payload: DevInstanceUpdate
) -> dict[str, Any]:
    del db, k8s
    row = await _get_or_404(None, id_)
    return await crud.update(
        None,
        row,
        display_name=payload.display_name,
        description=payload.description,
        env=payload.env,
    )


async def _get_or_404(db: Any, id_: Any) -> dict[str, Any]:
    del db
    row = await crud.get(None, id_)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"dev instance not found: {id_}"
        )
    return row


async def audit_devinstance(
    row: dict[str, Any],
    user: dict[str, Any] | None,
    operation: str,
    *,
    status_: str = "succeeded",
) -> None:
    """写一条开发机操作审计 (append-only, 失败不阻塞主流程)。

    operation: devinstance.create / .delete / .stop / .start
    scope_key 挂在所属 workspace 下 (admin 按 ws 查得到)。
    """
    from app.repositories import audit_log as audit_repo

    actor = user or {}
    actor_username = str(
        actor.get("username") or actor.get("user_id") or actor.get("id") or ""
    )
    try:
        await audit_repo.append(
            scope_key=_tables.scope_key_workspace(str(row.get("workspace_id") or "")),
            actor_user_id=actor_username,
            actor_role="platform-admin" if actor.get("is_admin") else "member",
            operation=operation,
            target_type="dev_instance",
            target_id=str(row.get("id") or ""),
            status=status_,
            metadata={
                "display_name": row.get("display_name") or "",
                "creator": row.get("creator_user_id") or "",
                "actor_email": actor.get("email") or "",
                "actor_display_name": actor.get("display_name") or "",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("dev_instance.audit_fail", op=operation,
                       id=str(row.get("id") or ""), err=str(exc))


async def _assert_can_operate(
    row: dict[str, Any], user: dict[str, Any] | None
) -> None:
    """开发机 stop/start/delete 的操作权限闸:
    creator 本人 OR ws 管理员 OR 平台超管 才放行, 否则 403。

    user=None 时跳过 (informer/worker 内部调用, 无用户上下文)。
    """
    if user is None:
        return
    username = str(
        user.get("user_id") or user.get("username") or user.get("id") or ""
    )
    if username and username == str(row.get("creator_user_id") or ""):
        return
    from app.core.security import is_ws_admin
    if await is_ws_admin(str(row.get("workspace_id") or ""), user):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        t("devinstance.forbidden_operate"),
    )


async def _assert_is_creator(
    row: dict[str, Any], user: dict[str, Any] | None
) -> None:
    """改规格专用: 仅创建者本人放行, 否则 403。

    比 _assert_can_operate 更严 — ws 管理员、平台超管都不行 (改规格会重建 Pod、
    改资源账单, 只让本人决定)。user=None 时跳过 (worker 内部调用, 无用户上下文)。
    """
    if user is None:
        return
    username = str(
        user.get("user_id") or user.get("username") or user.get("id") or ""
    )
    if username and username == str(row.get("creator_user_id") or ""):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        t("devinstance.forbidden_resize"),
    )
