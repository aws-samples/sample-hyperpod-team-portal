"""fsx-admin pod 命令执行封装 (配额操作复用此通道)。

配额命令 (mkdir/chown/chmod/lfs) 都在 fsx-admin pod 里跑 —— 该 pod 挂 FSx 根 +
带 CAP_SYS_ADMIN (lfs setquota 需要)。找 pod 逻辑复用 workspace 侧已有的
_resolve_fsx_admin_pod, 不重复实现。
"""

from __future__ import annotations

from app.adapters.k8s import K8sClient
from app.core.logging import get_logger
from app.modules.workspace.orchestration.fsx import _resolve_fsx_admin_pod

logger = get_logger(__name__)


async def run_admin_cmd(sh: str, timeout: int = 10) -> str | None:
    """在 fsx-admin pod 里跑一条 shell 命令, 返 stdout。

    exec_in_pod 失败/非零退出返 None (stderr 已合并进 stdout)。
    找不到 admin pod 也返 None。调用方据此判成败。
    """
    client = K8sClient()
    resolved = await _resolve_fsx_admin_pod(client)
    if not resolved:
        logger.info("fsx_quota.admin_cmd.no_pod")
        return None
    ns, pod_name, container = resolved
    return await client.exec_in_pod(
        namespace=ns,
        pod_name=pod_name,
        container=container,
        command=["sh", "-c", sh],
        timeout=timeout,
    )
