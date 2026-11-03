"""RayJob (Ray 训练) REST routes。与训练任务 UI 平级。

端点: list/create/preview/get/stop/delete + Pod 终端 WS (日志走 CloudWatch history)。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.i18n import t
from app.core.logging import get_logger
from app.core.security import (
    assert_ws_member,
    get_current_user,
)
from app.modules.quota.api.deps import get_hyperpod_client
from app.modules.rayjob.api.deps import get_k8s_client
from app.modules.rayjob.api.schemas import (
    RayJobCreate,
    RayJobDetail,
    RayJobListItem,
)
from app.modules.rayjob.orchestration import (
    create_rayjob_flow,
    delete_flow,
    preview_rayjob_flow,
    stop_flow,
    sync_from_k8s,
)
from app.modules.rayjob.persistence import crud
from app.modules.rayjob.response import build_detail, build_list_item
from app.modules.shared.kueue_status import pick_latest_pod
from app.services.hyperpod_client import HyperPodClient
from app.services.k8s_client import K8sClient

logger = get_logger(__name__)

rayjob_router = APIRouter(tags=["rayjob"])


@rayjob_router.get(
    "/workspaces/{ws_id}/rayjobs",
    response_model=list[RayJobListItem],
    summary="List Ray training jobs in workspace",
    description=(
        "按创建者过滤:\n"
        "- `scope=mine` (默认): 只返回当前用户创建的 Ray 任务\n"
        "- `scope=all`: 返回全 ws 所有 Ray 任务 · **需平台超管**\n\n"
        "`phase` 可选, 精确匹配 DDB 里存的 phase 字符串.\n\n"
        "⚠️ RayJob 目前**没有 informer / controller 回写 phase**: 创建后一直是 "
        "`initializing`, 只有调用 stop 才变 `Stopped`. 真实运行态要看详情接口 "
        "`sync=true` 返回的 `conditions` + `pods`.\n\n"
        "**纯读 DDB**, 不请求 K8s."
    ),
    responses={
        403: {"description": "非 ws 成员或超管; 或 scope=all 但非超管"},
    },
)
async def list_rayjobs(
    ws_id: str,
    phase: str | None = Query(default=None),
    scope: Literal["mine", "all"] = Query(default="mine"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[RayJobListItem]:
    await assert_ws_member(ws_id, current_user)
    if scope == "all":
        if not current_user.get("is_admin"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "scope=all requires admin; use scope=mine"
            )
        creator_filter: Any = None
    else:
        creator_filter = current_user.get("user_id") or current_user.get("id")
    rows = await crud.list_by_workspace(
        None, ws_id, phase=phase, creator_user_id=creator_filter
    )
    items = await asyncio.gather(*(build_list_item(None, r) for r in rows))
    return list(items)


@rayjob_router.post(
    "/workspaces/{ws_id}/rayjobs",
    response_model=RayJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a Ray training job (RayJob)",
    description=(
        "在 ws 内下发一个 KubeRay `RayJob` (head + N worker):\n"
        "1. 校验 `head_instance_type` / `worker_instance_type` 都在该 ws ComputeQuota 分配机型内\n"
        "2. 按引用反查授权真值: `fsx_mounts.pvc_name` → 该用户被授权的 FSx; "
        "`s3_datasets.mount_id` → ws 已挂 S3; `env_secrets` 补本人 `<user>-secrets` 并校验 key 存在\n"
        "3. 落 DDB (phase=`initializing`)\n"
        "4. 渲染并下发 RayJob CR (entrypoint = `bash <entry_script_path>`); 下发失败回滚 DDB 行\n\n"
        "任务名 = 用户传的 `name` 经 `sanitize_dns_label` 清洗 (**不加随机后缀、不查重**), "
        "同名重复提交会在 K8s 下发阶段失败 → 500."
    ),
    responses={
        400: {"description": "引用的 Secret key 不存在 (请先在 Secret 管理页添加)"},
        403: {
            "description": (
                "非 ws 成员或超管; 或 head/worker instance_type 不在该 ws ComputeQuota "
                "分配机型内; 或引用了未授权的 FSx / 未挂载的 S3"
            )
        },
        404: {"description": "Workspace 不存在; 或该 ws 无 ComputeQuota"},
        422: {"description": "请求体字段校验失败"},
        500: {"description": "K8s 下发 RayJob 失败 (含同名 CR 已存在); DDB 行已回滚"},
    },
)
async def create_rayjob(
    ws_id: str,
    payload: RayJobCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> RayJobDetail:
    await assert_ws_member(ws_id, current_user)
    row = await create_rayjob_flow(None, k8s, hp, ws_id, payload, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@rayjob_router.post(
    "/workspaces/{ws_id}/rayjobs/preview",
    summary="渲染最终 RayJob CR YAML, 不创建 (预览即真相)",
    description=(
        "与创建接口共用渲染逻辑 (`_render_cr`) → **预览即真相**. 只渲染不落库不下发, "
        "返回 `{\"yaml\": \"...\"}`.\n\n"
        "与 create 的差异: 预览里 `rayjob-id` label 是 `<preview>`; FSx/S3 授权反查失败**不报错**"
        "而是当空挂载渲染 (真 create 会拦 403); 也不校验 Secret key 是否存在.\n\n"
        "机型配额校验仍然生效 (head + worker 都查).\n\n"
        "前端创建表单最后一步用来给用户 diff 确认."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或 head/worker instance_type 不在配额机型内"
        },
        404: {"description": "Workspace 不存在; 或该 ws 无 ComputeQuota"},
        422: {"description": "请求体字段校验失败"},
    },
)
async def preview_rayjob(
    ws_id: str,
    payload: RayJobCreate,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    await assert_ws_member(ws_id, current_user)
    yaml_text = await preview_rayjob_flow(hp, ws_id, payload, current_user)
    return {"yaml": yaml_text}


@rayjob_router.get(
    "/rayjobs/{id}",
    response_model=RayJobDetail,
    summary="Get Ray job detail (默认读 DDB; sync=true 实时拉 CR conditions + pods)",
    description=(
        "默认 (`sync=false`) 纯读 DDB, 秒响应. 但 DDB 里的 phase 无人回写 "
        "(见列表接口说明), 想看真实进度必须 `sync=true`.\n\n"
        "`sync=true` 实时拉 `RayJob.status`: `conditions` 取 "
        "`status.rayClusterStatus.conditions`; Pods 用 `ray.io/cluster="
        "<status.rayClusterName>` 反查 (head+worker, 带 `role` 字段区分). "
        "**不回写 phase/kueue_status**.\n\n"
        "唯一的落库副作用: CR 已 404 且 `kueue_status` 非终态 (被 kubectl 绕过平台删掉) "
        "时把该行标成 `Stopped`."
    ),
    responses={
        403: {"description": "非该任务所属 ws 的成员且非超管"},
        404: {"description": "Ray 任务 id 不存在"},
    },
)
async def get_rayjob(
    id: str,
    sync: bool = Query(default=False),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> RayJobDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    conditions: list[dict[str, Any]] = []
    pods: list[dict[str, Any]] = []
    if sync:
        row, conditions, pods = await sync_from_k8s(None, k8s, row)
    return await build_detail(None, row, conditions=conditions, pods=pods)


@rayjob_router.get(
    "/rayjobs/{id}/status-detail",
    summary="Get Ray job raw status detail",
    description=(
        "按需单查 `status_detail` 全量 JSON = controller 落库的 `RayJob.status` "
        "原样快照, 状态列 debug 弹窗用.\n\n"
        "内容大, 因此不在 list 接口返回; 本接口只读 DDB, 不请求 K8s. "
        "controller 还没回写时返 `{\"status_detail\": null}`."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "Ray 任务不存在"},
    },
)
async def get_rayjob_status_detail(
    id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # 单独查 DDB 只返 status_detail (内容大, list 不返)。鉴权同 detail: assert_ws_member。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return {"status_detail": row.get("status_detail")}


@rayjob_router.get(
    "/rayjobs/{id}/kueue-detail",
    summary="Get Ray job Kueue workload detail",
    description=(
        "实时查该 Ray 任务背后的 Kueue Workload (`conditions` + `admission`), **不落库**.\n\n"
        "RayJob 1 跳 (同训练): Kueue Workload 经 ownerRef 直指 RayJob CR, "
        "`job-uid = CR.uid`. 找不到 CR / uid 时返 conditions=[], admission={}."
    ),
    responses={
        403: {"description": "非该任务所属 ws 的成员且非超管"},
        404: {"description": "Ray 任务 id 不存在"},
    },
)
async def get_rayjob_kueue_detail(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # RayJob 1 跳: CR uid = job-uid (Kueue Workload ownerRef 直指 RayJob, 同训练)。
    # 实时查 Workload, 返当前 conditions + admission (不落库)。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    ns = row.get("k8s_namespace") or ""
    cr_name = row.get("k8s_cr_name") or ""
    conditions: list[dict[str, Any]] = []
    admission: dict[str, Any] = {}
    if ns and cr_name:
        try:
            cr = await k8s.get_rayjob(ns, cr_name)
            uid = ((cr or {}).get("metadata") or {}).get("uid") or ""
            if uid:
                wls = await k8s.list_workloads_by_job_uid(ns, uid)
                wl = pick_latest_pod(wls)
                wl_status = (wl or {}).get("status") or {}
                conditions = wl_status.get("conditions") or []
                admission = wl_status.get("admission") or {}
        except Exception as exc:  # noqa: BLE001
            logger.info("rayjob.kueue_detail.skip", id=str(id), err=str(exc))
    return {"conditions": conditions, "admission": admission}


@rayjob_router.post(
    "/rayjobs/{id}/stop",
    response_model=RayJobDetail,
    summary="Stop (删 RayJob CR, KubeRay 级联回收 pod, 保留 DDB 行 phase=Stopped)",
    description=(
        "先把 DDB 行标 phase=`Stopped` + `kueue_status=Finished` + `stop_requested` 哨兵, "
        "再删 `RayJob` CR (KubeRay 级联回收 RayCluster + head/worker pod). "
        "DDB 行与全部 spec 保留 (不软删), 供查日志 + 克隆重跑.\n\n"
        "**幂等**: CR 已不在 (K8s 404) 照样返回已标 Stopped 的行 "
        "(RayJob 跑完 `shutdownAfterJobFinishes` 会自己拆 CR, 这种情况很常见).\n\n"
        "返回体同详情接口 (`conditions`/`pods` 为空, 不实时拉 K8s)."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "Ray 任务 id 不存在"},
        500: {"description": "K8s 删除 RayJob 失败 (非 404)"},
    },
)
async def stop_rayjob(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> RayJobDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    row = await stop_flow(None, k8s, id, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@rayjob_router.delete(
    "/rayjobs/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Ray job (cascade RayJob CR + RayCluster + pods)",
    description=(
        "删 `RayJob` CR (KubeRay 级联回收 RayCluster + pods), 然后**软删** DDB 行: "
        "打 `deleted_at` 标记, 不硬删 — 列表页过滤掉, 审计仍可查.\n\n"
        "**幂等**: CR 已不存在 (K8s 404) 视为成功照样删行 — RayJob 跑完 "
        "`shutdownAfterJobFinishes` 已自拆 CR, 否则任务一跑完就永远删不掉.\n\n"
        "**权限**: 端点层要求 ws 成员或超管; 内部再校验 creator 本人 / ws 管理员 / 平台超管."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "Ray 任务 id 不存在"},
        500: {"description": "K8s 删除 RayJob 失败 (非 404)"},
    },
)
async def delete_rayjob(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"rayjob not found: {id}")
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    await delete_flow(None, k8s, id, current_user)
    return None


# ── Pod 交互终端 (WS exec -it, 照训练) ──
# auth_middleware 不拦 WS, 自己验 ?access_token=; container 默认 ray-head。
import asyncio  # noqa: E402
import json  # noqa: E402

from fastapi import WebSocket, WebSocketDisconnect  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import (  # noqa: E402
    _api_token_user,
    _user_from_cognito_token,
    resolve_user_token,
)
from app.core.token_util import TOKEN_PREFIX  # noqa: E402

_TERMINAL_IDLE_SECONDS = 300  # 5min 无 stdin 断
_TERMINAL_MAX_PER_USER = 3
_terminal_conns: dict[str, int] = {}


async def _ws_user(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        if token.startswith(TOKEN_PREFIX):
            return await _api_token_user(token)
        return await _user_from_cognito_token(token, get_settings())
    except Exception:  # noqa: BLE001
        return None


@rayjob_router.websocket("/rayjobs/{id}/pods/{pod}/terminal")
async def rayjob_pod_terminal(
    websocket: WebSocket,
    id: str,  # noqa: A002
    pod: str,
    container: str = Query(default="ray-head"),
) -> None:
    token = resolve_user_token("", websocket.query_params.get("access_token"))
    user = await _ws_user(token or "")
    if user is None:
        await websocket.close(code=4401)
        return

    row = await crud.get(None, id)
    if row is None:
        await websocket.close(code=4404)
        return
    try:
        await assert_ws_member(str(row.get("workspace_id")), user)
    except HTTPException:
        await websocket.close(code=4403)
        return
    namespace = row.get("k8s_namespace") or "default"

    uid = str(user.get("user_id") or user.get("id") or "")
    if _terminal_conns.get(uid, 0) >= _TERMINAL_MAX_PER_USER:
        await websocket.close(code=4429)
        return

    await websocket.accept()
    _terminal_conns[uid] = _terminal_conns.get(uid, 0) + 1
    k8s = get_k8s_client()

    async def _pump(ws: Any) -> None:
        async def _browser_to_pod() -> None:
            while True:
                try:
                    msg = await asyncio.wait_for(
                        websocket.receive(), timeout=_TERMINAL_IDLE_SECONDS
                    )
                except asyncio.TimeoutError:
                    return
                if msg.get("type") == "websocket.disconnect":
                    return
                data = msg.get("text") or msg.get("bytes")
                if data is None:
                    continue
                if isinstance(data, str):
                    if data.startswith("{") and "resize" in data:
                        try:
                            r = json.loads(data)["resize"]
                            payload = json.dumps({"Width": r["cols"], "Height": r["rows"]})
                            await ws.send_bytes(b"\x04" + payload.encode())
                            continue
                        except Exception:  # noqa: BLE001
                            pass
                    await ws.send_bytes(b"\x00" + data.encode())
                else:
                    await ws.send_bytes(b"\x00" + bytes(data))

        async def _pod_to_browser() -> None:
            async for wsmsg in ws:
                raw = wsmsg.data
                if not raw or len(raw) < 2:
                    continue
                if raw[0] in (1, 2):
                    await websocket.send_bytes(raw[1:])

        t1 = asyncio.create_task(_browser_to_pod())
        t2 = asyncio.create_task(_pod_to_browser())
        _done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    connected = False
    try:
        for shell in ("/bin/bash", "/bin/sh"):
            try:
                exec_ws = await k8s.exec_interactive(namespace, pod, container, [shell])
                async with exec_ws as ws:
                    connected = True
                    await _pump(ws)
                break
            except WebSocketDisconnect:
                raise
            except Exception as exc:  # noqa: BLE001
                if connected:
                    raise
                logger.info("rayjob.terminal.shell_fail", pod=pod, shell=shell, err=str(exc))
                continue
        if not connected:
            try:
                await websocket.send_text(f"\r\n{t('core.terminal_unavailable')}\r\n")
                await websocket.close(code=4500)
            except Exception:  # noqa: BLE001
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.info("rayjob.terminal.error", id=str(id), pod=pod, err=str(exc))
    finally:
        _terminal_conns[uid] = max(0, _terminal_conns.get(uid, 1) - 1)
