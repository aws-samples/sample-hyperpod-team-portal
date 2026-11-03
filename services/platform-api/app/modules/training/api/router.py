"""TrainingJob REST routes (DDB-only)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.core.i18n import t
from app.core.logging import get_logger
from app.core.security import (
    assert_ws_member,
    get_current_user,
    resolve_user_token,
)
from app.modules.quota.api.deps import get_hyperpod_client
from app.modules.shared.kueue_status import pick_latest_pod
from app.modules.training.api.deps import get_k8s_client
from app.modules.training.api.schemas import (
    TopologyLevel,
    TrainingJobCreate,
    TrainingJobDetail,
    TrainingJobListItem,
)
from app.modules.training.domain.cr import RunPolicyValidationError
from app.modules.training.orchestration import (
    create_training_job_flow,
    delete_flow,
    preview_training_job_flow,
    resolve_topology_levels,
    stop_flow,
)
from app.modules.training.persistence import crud
from app.modules.training.response import build_detail, build_list_item
from app.services.hyperpod_client import HyperPodClient
from app.services.k8s_client import K8sClient

logger = get_logger(__name__)

training_router = APIRouter(tags=["training-jobs"])


@training_router.get(
    "/workspaces/{ws_id}/training-jobs",
    response_model=list[TrainingJobListItem],
    summary="List training jobs in workspace",
    description=(
        "按创建者过滤:\n"
        "- `scope=mine` (默认): 只返回当前用户创建的训练任务\n"
        "- `scope=all`: 返回全 ws 所有训练任务 · **需超管**\n\n"
        "`phase` 可选, 精确匹配任务态. 取值 = CR `status.conditions` 里 status=True 的 type "
        "(`Created` / `Running` / `Complete` / `Failed` / `Suspended`), 外加平台自己写的 "
        "`Pending` (刚创建, informer 还没回写) 与 `Stopped` (调用 stop).\n\n"
        "**纯读 DDB** — platform-worker informer 实时维护 phase, 不再 request-driven sync K8s."
    ),
    responses={
        403: {"description": "非 ws 成员; 或 scope=all 但非超管"},
    },
)
async def list_training_jobs(
    ws_id: str,
    phase: str | None = Query(default=None),
    scope: Literal["mine", "all"] = Query(default="mine"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[TrainingJobListItem]:
    # 纯读 DDB · phase 由 platform-worker informer 实时维护 (不再 request-driven sync)。
    # 非 ws 成员一律 403 (越权修复 2026-06-14), 不再泄露 ws 是否存在。
    await assert_ws_member(ws_id, current_user)
    if scope == "all":
        if not current_user.get("is_admin"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "scope=all requires admin; use scope=mine",
            )
        creator_filter: Any = None
    else:
        creator_filter = current_user.get("user_id") or current_user.get("id")

    rows = await crud.list_by_workspace(
        None, ws_id, phase=phase, creator_user_id=creator_filter
    )

    import asyncio

    # build_list_item 并发 (每 row 可能 2 次 DDB GetItem; gather 省串行耗时)。
    items = await asyncio.gather(*(build_list_item(None, r) for r in rows))
    return list(items)


@training_router.post(
    "/workspaces/{ws_id}/training-jobs",
    response_model=TrainingJobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create training job",
    description=(
        "在 ws 内下发一个分布式训练任务:\n"
        "1. 渲染 `HyperPodPyTorchJob` CR (FSx/S3 挂载, replica/资源规格, Secret env). "
        "**默认 `auto_wrap=false` → `command` 原样下发, 平台不套 `hyperpodrun`** "
        "(用户自管启动器); 传 `auto_wrap=true` 才把命令包进 `hyperpodrun`.\n"
        "2. 落 DDB (phase=`Pending`)\n"
        "3. 提交 K8s, 走 Kueue 排队 (LocalQueue → ClusterQueue), HyperPod operator 接手调度\n\n"
        "任务名不查重: `name` = `display_name` + `-` + 10 位随机后缀, 由后端派生 "
        "(请勿自己传 `name`), 创建成功后从响应的 `name` 读真实任务名.\n\n"
        "创建成功即返 phase=`Pending`; 后续状态靠 platform-worker informer 推进."
    ),
    responses={
        400: {
            "description": (
                "引用的 Secret key 不存在; 或 topology_label 不在该机型可用层级内"
            )
        },
        403: {
            "description": (
                "非 ws 成员或超管; 或 instance_type 不在该 ws ComputeQuota 分配机型内; "
                "或引用了未授权的 FSx / 未挂载的 S3"
            )
        },
        404: {"description": "Workspace 不存在"},
        422: {"description": "请求体字段校验失败 (启动命令 / 资源规格 / 名称等)"},
        500: {
            "description": (
                "K8s 下发 HyperPodPyTorchJob 失败 (DDB 行已回滚); "
                "或 `run_policy_override` 非法 (未捕获的 RunPolicyValidationError)"
            )
        },
    },
)
async def create_training_job(
    ws_id: str,
    payload: TrainingJobCreate,
    k8s: K8sClient = Depends(get_k8s_client),
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TrainingJobDetail:
    # 仅 ws 成员或超管可在此 ws 提交训练任务 (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    row = await create_training_job_flow(None, k8s, hp, ws_id, payload, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


@training_router.post(
    "/workspaces/{ws_id}/training-jobs/preview",
    summary="Preview training job CR YAML",
    description=(
        "与创建接口共用渲染逻辑 (`_render_cr`) → **预览即真相**, 所见即所得. "
        "只渲染不落库不下发, 返回 `{\"yaml\": \"...\"}`.\n\n"
        "预览里的任务名是占位 `<display_name>-xxxxxxxxxx` (真名只在 create 时派生一次), "
        "`training-job-id` label 为 `<preview>`. 预览也不校验 Secret key 是否存在.\n\n"
        "前端创建表单最后一步用来给用户 diff 确认 CR 细节 (启动命令 / 资源 / 挂载 / runPolicy 等)."
    ),
    responses={
        403: {
            "description": (
                "非 ws 成员或超管; 或 instance_type 不在配额机型内; "
                "或引用了未授权的 FSx / 未挂载的 S3"
            )
        },
        404: {"description": "Workspace 不存在"},
        422: {
            "description": (
                "请求体字段校验失败; 或 `run_policy_override` 非法 (越权字段 / 类型错 / 缺 required)"
            )
        },
    },
)
async def preview_training_job(
    ws_id: str,
    payload: TrainingJobCreate,
    hp: HyperPodClient = Depends(get_hyperpod_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """渲染最终要下发的 CR YAML, 不创建。与 create 共用渲染 → 预览即真相。"""
    # 仅 ws 成员或超管可预览 (会泄露 ws namespace 等内部配置) (越权修复 2026-06-14)
    await assert_ws_member(ws_id, current_user)
    try:
        yaml_text = await preview_training_job_flow(hp, ws_id, payload, current_user)
    except RunPolicyValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc
    return {"yaml": yaml_text}


@training_router.get(
    "/workspaces/{ws_id}/training-jobs/topology-levels",
    response_model=list[TopologyLevel],
    summary="该机型可用的拓扑层级",
    description=(
        "按实例类型返回可用的 Kueue 拓扑层级, 由细到粗 (层号越大越靠近实例).\n\n"
        "数据源: `ResourceFlavor(name==instance_type).spec.topologyName` → "
        "`Topology.spec.levels[].nodeLabel`, 读集群真值不做白名单.\n\n"
        "返回空列表 = 无可选层级 (查不到 flavor / 未绑 topologyName / 查不到 Topology / "
        "只有一级), 前端据此置灰.\n\n"
        "选中的层级在创建时校验必须 ∈ 本接口返回集合, 并渲进 CR pod 注解 "
        "`kueue.x-k8s.io/podset-{required,preferred}-topology` (仅 p5+/trn 生效, g6 静默忽略).\n\n"
        "**权限**: 仅 ws 成员或超管."
    ),
    responses={403: {"description": "非 ws 成员或超管"}},
)
async def get_topology_levels_endpoint(
    ws_id: str,
    instance_type: str = Query(..., description="实例类型, 如 ml.g6.12xlarge"),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[TopologyLevel]:
    """该机型可用层级; 空列表 = 无可选。"""
    await assert_ws_member(ws_id, current_user)
    return await resolve_topology_levels(k8s, instance_type)


@training_router.get(
    "/training-jobs/{id}",
    response_model=TrainingJobDetail,
    summary="Get training job detail",
    description=(
        "phase / 基础字段 **纯读 DDB** (informer 实时维护).\n\n"
        "`live=true` (默认) 时额外实时只读拉 K8s `HyperPodPyTorchJob.status.conditions` + Pods "
        "(详情页状态时间线 / Pod 表用, 单次 ~200-500ms, **不写 DDB**).\n"
        "`live=false` 跳过 K8s 请求, 只返 DDB 结果 (秒响应, 列表页跳详情预热用)."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
    },
)
async def get_training_job(
    id: str,
    live: bool = Query(
        default=True,
        description=(
            "True (默认) 实时只读拉 K8s pods + conditions (详情页特有, ~200-500ms 单次, "
            "不写 DDB)。False 跳过, 只返 DDB 里的 phase/基础字段 (秒响应)。"
            "phase 由 platform-worker informer 维护, 不在此 sync。"
        ),
    ),
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TrainingJobDetail:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    # 仅该 job 所属 ws 的成员或超管可看 (越权修复 2026-06-14)
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    conditions: list[dict[str, Any]] = []
    pods: list[dict[str, Any]] = []
    if live and row.get("k8s_namespace") and row.get("k8s_job_name"):
        # 只读 CR.status.conditions + pods (不写 DDB; phase 归 informer 维护)
        try:
            cr = await k8s.get_hyperpod_pytorch_job(
                row["k8s_namespace"], row["k8s_job_name"]
            )
            conditions = (cr.get("status") or {}).get("conditions") or []
        except Exception as exc:
            logger.info("training.get.cr_read_skip", id=str(id), err=str(exc))
        try:
            pods = await k8s.list_pods_by_label_selector(
                row["k8s_namespace"], f"HPJob={row['k8s_job_name']}"
            )
        except Exception as exc:
            logger.info("training.get.pods_read_skip", id=str(id), err=str(exc))
    return await build_detail(None, row, conditions=conditions, pods=pods)


@training_router.get(
    "/training-jobs/{id}/status-detail",
    summary="Get training job raw status detail",
    description=(
        "按需单查 `status_detail` 全量 JSON = informer 落库的 `HyperPodPyTorchJob.status` "
        "原样快照 (含原始 conditions), 详情页 debug 弹窗用.\n\n"
        "内容大, 因此不在 list 接口返回; 本接口只读 DDB, 不请求 K8s. "
        "informer 还没回写时返 `{\"status_detail\": null}`."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
    },
)
async def get_training_status_detail(
    id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # 单独查 DDB 只返 status_detail (内容大, list 不返)。鉴权同 detail: assert_ws_member。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    return {"status_detail": row.get("status_detail")}


@training_router.get(
    "/training-jobs/{id}/kueue-detail",
    summary="Get training job Kueue workload detail",
    description=(
        "实时查该训练任务背后的 Kueue Workload (`conditions` + `admission`), **不落库**.\n\n"
        "训练 1 跳: CR uid = job-uid → Workload. 找不到 CR / uid 时返 conditions=[], admission={}."
    ),
    responses={
        403: {"description": "非 ws 成员或超管"},
        404: {"description": "训练任务不存在"},
    },
)
async def get_training_kueue_detail(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    # 训练 1 跳: CR uid = job-uid。实时查 Workload, 返当前 conditions + admission (不落库)。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    ns = row.get("k8s_namespace") or ""
    cr_name = row.get("k8s_job_name") or ""
    conditions: list[dict[str, Any]] = []
    admission: dict[str, Any] = {}
    if ns and cr_name:
        try:
            cr = await k8s.get_hyperpod_pytorch_job(ns, cr_name)
            uid = ((cr or {}).get("metadata") or {}).get("uid") or ""
            if uid:
                wls = await k8s.list_workloads_by_job_uid(ns, uid)
                wl = pick_latest_pod(wls)
                wl_status = (wl or {}).get("status") or {}
                conditions = wl_status.get("conditions") or []
                admission = wl_status.get("admission") or {}
        except Exception as exc:
            logger.info("training.kueue_detail.skip", id=str(id), err=str(exc))
    return {"conditions": conditions, "admission": admission}


@training_router.delete(
    "/training-jobs/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除训练任务",
    description=(
        "删 `HyperPodPyTorchJob` CR (operator 级联 Pods + 关联 Kueue Workload), "
        "然后**软删** DDB 行: 打 `deleted_at` 标记, 不硬删 — 列表页过滤掉, 审计仍可查. "
        "同时清该任务的分享记录 (best-effort, 失败不阻塞).\n\n"
        "**幂等**: CR 已不存在 (K8s 404) 视为成功, 重复删同一行仍返 204.\n\n"
        "**权限**: 端点层要求 ws 成员或超管; 内部再校验 creator 本人 / ws 管理员 / 平台超管."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "训练任务 id 不存在"},
        500: {"description": "K8s 删除 HyperPodPyTorchJob 失败"},
    },
)
async def delete_training_job(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    # 删前先校验调用者是该 job 所属 ws 的成员/超管 (越权修复 2026-06-14):
    # 端点层快速失败; delete_flow 内部 _assert_can_operate + audit_training 再兜底+留痕。
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    await delete_flow(None, k8s, id, current_user)
    return None


@training_router.post(
    "/training-jobs/{id}/stop",
    summary="停止训练任务 (保留 DDB 行)",
    description=(
        "先把 DDB 行标 phase=`Stopped` + `kueue_status=Finished` + `stop_requested` 哨兵, "
        "再删 `HyperPodPyTorchJob` CR (operator 级联 Pod) 释放 GPU 停计费. "
        "DDB 行保留 (不软删), spec 完整留着供查日志 + 克隆重跑.\n\n"
        "先标后删的顺序是必须的: 否则 informer 收到 DELETED 时哨兵未置 → 会被当成删除软删掉.\n\n"
        "**非暂停恢复** — 训练无 resume, 停了只能 clone 出新任务.\n\n"
        "**幂等**: CR 已不在 (K8s 404) 照样返回已标 Stopped 的行.\n\n"
        "返回体同详情接口 (`conditions`/`pods` 为空, 不实时拉 K8s)."
    ),
    responses={
        403: {
            "description": "非 ws 成员或超管; 或非创建者本人且非 ws 管理员 / 平台超管"
        },
        404: {"description": "训练任务 id 不存在"},
        500: {"description": "K8s 删除 HyperPodPyTorchJob 失败 (非 404)"},
    },
)
async def stop_training_job(
    id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> Any:
    row = await crud.get(None, id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"training job not found: {id}"
        )
    await assert_ws_member(str(row.get("workspace_id")), current_user)
    row = await stop_flow(None, k8s, id, current_user)
    return await build_detail(None, row, conditions=[], pods=[])


# ===== Pod 交互式 Terminal =====
# WebSocket exec -it 进训练 pod。auth_middleware 不拦 WS, 自己验 ?access_token=。
# k8s channel 协议: 帧首字节 channel (0 stdin/1 stdout/2 stderr/3 err/4 resize)。

import asyncio
import json

from app.core.config import get_settings
from app.core.security import _api_token_user, _user_from_cognito_token
from app.core.token_util import TOKEN_PREFIX

_TERMINAL_IDLE_SECONDS = 300  # 5min 无 stdin 输入断
_TERMINAL_MAX_PER_USER = 3
_terminal_conns: dict[str, int] = {}  # user_id -> 活跃 terminal 连接数


async def _ws_user(token: str) -> dict[str, Any] | None:
    """从 token 解析用户 (api-token / cognito 双路), 失败返 None。"""
    if not token:
        return None
    try:
        if token.startswith(TOKEN_PREFIX):
            return await _api_token_user(token)
        return await _user_from_cognito_token(token, get_settings())
    except Exception:  # noqa: BLE001
        return None


@training_router.websocket("/training-jobs/{id}/pods/{pod}/terminal")
async def training_pod_terminal(
    websocket: WebSocket,
    id: str,  # noqa: A002
    pod: str,
    container: str = Query(default="trainer"),
) -> None:
    token = resolve_user_token("", websocket.query_params.get("access_token"))
    user = await _ws_user(token or "")
    if user is None:
        await websocket.close(code=4401)
        return

    job = await crud.get(None, id)
    if job is None:
        await websocket.close(code=4404)
        return
    try:
        await assert_ws_member(str(job.get("workspace_id")), user)
    except HTTPException:
        await websocket.close(code=4403)
        return
    namespace = job.get("k8s_namespace") or "default"

    uid = str(user.get("user_id") or user.get("id") or "")
    if _terminal_conns.get(uid, 0) >= _TERMINAL_MAX_PER_USER:
        await websocket.close(code=4429)  # 自定义 "too many connections"
        return

    await websocket.accept()
    _terminal_conns[uid] = _terminal_conns.get(uid, 0) + 1
    from app.modules.training.orchestration.lifecycle import audit_training
    await audit_training(job, user, "training.terminal.open")

    k8s = get_k8s_client()

    async def _pump(ws: Any) -> None:  # nosemgrep: useless-inner-function — 误报: 下方 `await _pump(ws)` 真实调用
        async def _browser_to_pod() -> None:
            while True:
                try:
                    msg = await asyncio.wait_for(
                        websocket.receive(), timeout=_TERMINAL_IDLE_SECONDS
                    )
                except asyncio.TimeoutError:
                    return  # 空闲超时 → 结束 → 上层 cancel pod 端 + 清理
                if msg.get("type") == "websocket.disconnect":
                    return
                data = msg.get("text") or msg.get("bytes")
                if data is None:
                    continue
                if isinstance(data, str):
                    # resize: 前端发 {"resize":{"cols":..,"rows":..}}
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
                if raw[0] in (1, 2):  # stdout / stderr
                    await websocket.send_bytes(raw[1:])

        # 任一方向结束 (浏览器关 / pod 退出) → 取消另一方向, 避免往已关 WS 再 send
        # (ASGI "websocket.send after close" 报错根因)。
        t1 = asyncio.create_task(_browser_to_pod())
        t2 = asyncio.create_task(_pod_to_browser())
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    # connect_get_namespaced_pod_exec 是延迟连接: 真正握手在 `async with` 时发生,
    # 故 bash/sh fallback 要在进 ws 那步判 (崩溃容器/无 shell 都在此报)。
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
                logger.info("training.terminal.shell_fail", pod=pod, shell=shell, err=str(exc))
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
        logger.info("training.terminal.error", id=str(id), pod=pod, err=str(exc))
    finally:
        _terminal_conns[uid] = max(0, _terminal_conns.get(uid, 1) - 1)
        await audit_training(job, user, "training.terminal.close")
