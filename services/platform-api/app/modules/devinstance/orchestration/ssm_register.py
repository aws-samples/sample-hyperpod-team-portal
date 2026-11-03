"""DevInstance SSM 主动注册编排 (绕开 spaces 0.1.5 sidecar 死锁).

设计上下文:
    spaces operator v0.1.5 sidecar entrypoint 只 sleep infinity, 期望 controller
    在 reconcile 时给它推 SSM activation. 但 controller 等 deployment ready,
    sidecar 等 ssm-agent 跑 (readiness), ssm-agent 等 activation 注入 — 死锁.

    本模块绕开: 平台直接调 ssm:CreateActivation + kubectl exec sidecar 跑
    register-ssm.sh, 然后 touch /tmp/ssm-registered (AWS 自己脚本 bug:
    register-ssm.sh 创 /tmp/ssm-instance-id 但 readiness probe 找
    /tmp/ssm-registered, 命名不一致).
    坑 15.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.aws.ssm import create_activation
from app.adapters.k8s import K8sClient
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


_SIDECAR_CONTAINER = "ssm-agent-sidecar"
_WORKSPACE_CONTAINER = "workspace"
_REGISTER_SCRIPT = "/usr/local/bin/register-ssm.sh"
_READY_MARKER = "/tmp/ssm-registered"
_RAS_SCRIPT = (
    "/opt/amazon/sagemaker/workspace/remote-access/start-remote-access-server.sh"
)
_RAS_BIN = (
    "/opt/amazon/sagemaker/workspace/remote-access/remote-access-server"
)
# sidecar pod 起来 (容器 spec 出现 + 至少一次 schedule 完成) 通常 30-60s
# 等 sidecar running 的上限 (轮询, 一旦 running 立即返回, 不是固定等这么久).
# sidecar 要等主镜像拉完才启动; 用户自定义大镜像首次拉取可能 ~8min,
# 给 600s (10min) 覆盖. 全程后台异步, 不阻塞创建请求.
_SIDECAR_READY_TIMEOUT_SEC = 600
_SIDECAR_POLL_INTERVAL_SEC = 3
# register-ssm.sh exec 偶发失败 (wss 抖动) 时的重试次数.
_REGISTER_MAX_ATTEMPTS = 3
_REGISTER_RETRY_DELAY_SEC = 3


async def register_ssm_in_sidecar(
    k8s: K8sClient, instance: dict[str, Any]
) -> str | None:
    """主动给 sidecar 注入 SSM activation, 返回 mi-xxx (managed instance id).

    流程:
        1. 等 sidecar 容器存在 (Pod 创建 + 调度完成)
        2. ssm:CreateActivation 拿 (id, code)
        3. kubectl exec sidecar -- env ID=.. CODE=.. REGION=.. register-ssm.sh
        4. touch /tmp/ssm-registered (绕过 readiness probe AWS 脚本不一致 bug)
        5. exec read /tmp/ssm-instance-id 拿 mi-xxx 返回

    失败时返 None, 不抛 (上层调用方按"未就绪"处理). 异常已 logger 记录.
    """
    inst_id = str(instance.get("id") or "")
    namespace = instance["k8s_namespace"]
    workspace_name = instance["k8s_workspace_name"]

    # 1. 等 sidecar 容器存在
    pod_name = await _wait_sidecar_present(k8s, namespace, workspace_name, inst_id)
    if pod_name is None:
        logger.warning(
            "ssm_register.sidecar_timeout",
            id=inst_id,
            ns=namespace,
            workspace=workspace_name,
        )
        return None

    # 2. SSM CreateActivation
    settings = get_settings()
    description = (
        f"hyperpod-platform/{settings.eks_cluster_name or 'unknown'}/"
        f"{namespace}/{workspace_name} (dev-instance {inst_id})"
    )
    try:
        act = await create_activation(description)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ssm_register.create_activation_fail",
            id=inst_id,
            err=str(exc),
        )
        return None

    # 3. kubectl exec register-ssm.sh
    cmd = [
        "env",
        f"ACTIVATION_ID={act['activation_id']}",
        f"ACTIVATION_CODE={act['activation_code']}",
        f"REGION={settings.aws_region}",
        _REGISTER_SCRIPT,
    ]
    # exec 偶发失败 (wss 抖动 / 容器刚 running 还没完全就绪) 时重试几次.
    out: str | None = None
    for attempt in range(1, _REGISTER_MAX_ATTEMPTS + 1):
        try:
            out = await k8s.exec_in_pod(
                namespace=namespace,
                pod_name=pod_name,
                container=_SIDECAR_CONTAINER,
                command=cmd,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ssm_register.exec_error",
                id=inst_id,
                pod=pod_name,
                attempt=attempt,
                err=str(exc),
            )
            out = None
        if out and "Registration successful" in out:
            break
        if attempt < _REGISTER_MAX_ATTEMPTS:
            await asyncio.sleep(_REGISTER_RETRY_DELAY_SEC)
    if not out or "Registration successful" not in out:
        logger.warning(
            "ssm_register.script_fail",
            id=inst_id,
            pod=pod_name,
            attempts=_REGISTER_MAX_ATTEMPTS,
            out_excerpt=(out or "")[:200],
        )
        return None

    # 4. touch /tmp/ssm-registered (AWS 命名不一致 bug 绕过)
    await k8s.exec_in_pod(
        namespace=namespace,
        pod_name=pod_name,
        container=_SIDECAR_CONTAINER,
        command=["touch", _READY_MARKER],
        timeout=5,
    )

    # 5. 在主容器 (workspace) 启 remote-access-server (不是在 sidecar 里启).
    # 为啥不在 sidecar:
    #   sidecar 是最小镜像没 tar/python, ssh 进去 vscode-server 装不了 (报
    #   "tar: command not found"). 主容器 sagemaker-distribution 工具齐全.
    # K8s Pod 里所有容器共享 network namespace, 主容器 :2222 sidecar 也能访问;
    # SSM 隧道转发到 127.0.0.1:2222 自动落到主容器, 不影响 SSM 那边.
    # 主容器 EBS PVC 挂在 /opt/amazon/sagemaker/workspace/remote-access/, 共享
    # sidecar entrypoint 复制过来的 binary 和 script.
    # nohup + & 把 server detach 出 exec session, exec 退出 server 还活着.
    # 5a. 检查 RAS 是否已经在跑 (pgrep 走单独 exec 避免 self-match: 整条
    # bash -c "..." 的 cmdline 含字面 remote-access-server, 同一进程 pgrep
    # 会命中自己, 所以拆成两次 exec).
    check_out = await k8s.exec_in_pod(
        namespace=namespace,
        pod_name=pod_name,
        container=_WORKSPACE_CONTAINER,
        command=[
            "bash", "-c",
            "pgrep -f 'remote-acce[s]s-server' >/dev/null && echo running || echo absent",
        ],
        timeout=10,
    )
    if not check_out or "absent" in check_out:
        # 5b. RAS 没跑, 启之. setsid + nohup + < /dev/null: K8s exec
        # websocket 关闭时不带走子进程 (单 nohup 被 SIGHUP 误杀过).
        await k8s.exec_in_pod(
            namespace=namespace,
            pod_name=pod_name,
            container=_WORKSPACE_CONTAINER,
            command=[
                "bash", "-c",
                (
                    f"setsid nohup {_RAS_BIN} -port 2222 "
                    "  < /dev/null > /tmp/ras.log 2>&1 & "
                    "disown; "
                    "sleep 1; "
                    "echo started"
                ),
            ],
            timeout=15,
        )

    # 6. 读 mi-xxx
    mi_raw = await k8s.exec_in_pod(
        namespace=namespace,
        pod_name=pod_name,
        container=_SIDECAR_CONTAINER,
        command=["cat", "/tmp/ssm-instance-id"],
        timeout=5,
    )
    mi = (mi_raw or "").strip()
    if not mi.startswith("mi-"):
        logger.warning(
            "ssm_register.mi_missing", id=inst_id, raw=(mi_raw or "")[:80]
        )
        return None

    logger.info(
        "ssm_register.ok", id=inst_id, mi=mi, pod=pod_name
    )
    return mi


async def _wait_sidecar_present(
    k8s: K8sClient,
    namespace: str,
    workspace_name: str,
    inst_id: str,
) -> str | None:
    """轮询直到 sidecar 容器进程**已启动 (state.running)**, 返 pod 名.

    不能只看"存在": 大镜像拉取时 sidecar 容器条目早早出现 (状态 waiting),
    此时 exec 进去跑 register-ssm.sh 会 500 (容器还没真正 running).
    也不能等 ready: sidecar readinessProbe 检查 /tmp/ssm-registered, 而该文件
    正是注册成功后第 4 步才 touch 的 → 等 ready 会死锁 (注册没跑→文件没建→
    永不 ready). 正确条件 = 容器进程已 running (能 exec 即可, 不依赖注册).
    """
    deadline = asyncio.get_event_loop().time() + _SIDECAR_READY_TIMEOUT_SEC
    while asyncio.get_event_loop().time() < deadline:
        try:
            pod = await k8s.get_pod_by_workspace(namespace, workspace_name)
        except Exception:  # noqa: BLE001
            pod = None
        if pod:
            pod_name = (pod.get("metadata") or {}).get("name")
            statuses = (pod.get("status") or {}).get(
                "container_statuses"
            ) or (pod.get("status") or {}).get("containerStatuses") or []
            sidecar_running = any(
                cs.get("name") == _SIDECAR_CONTAINER
                and ((cs.get("state") or {}).get("running") is not None)
                for cs in statuses
            )
            if pod_name and sidecar_running:
                return pod_name
        await asyncio.sleep(_SIDECAR_POLL_INTERVAL_SEC)
    return None
