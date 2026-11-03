"""把用户 SSH 公钥写入开发机 ~/.ssh/authorized_keys (代执行 pod 内命令)。

原本用户要自己打开 code editor 终端粘一串命令; 这里平台代跑, 用户在连接弹窗填公钥即可。
访问闸与"能打开 code editor"一致: 创建者本人 / 平台超管 / 被创建者分享的人 (不含 ws-admin,
分享是 creator 私有授权, ws-admin 不自动获得别人开发机的 shell)。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.adapters.k8s import K8sAPIError, K8sClient
from app.core.i18n import t
from app.core.logging import get_logger

from .lifecycle import _get_or_404

logger = get_logger(__name__)

# operator 给 Workspace Pod 主容器固定命名 workspace (与 ssm_register 同源)。
_WORKSPACE_CONTAINER = "workspace"

# 公钥经 argv $1 传入 (不拼进脚本文本) → 彻底杜绝 shell 注入; grep -qxF 整行去重 → 幂等。
# home 目录属 uid 1000 (sagemaker-user), ~ 正常解析。echo 尾标供判定成功 (exec 无输出时
# 无法区分成功/失败)。
_APPEND_KEY_SCRIPT = (
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
    "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
    'if ! grep -qxF "$1" ~/.ssh/authorized_keys; then '
    'printf "%s\\n" "$1" >> ~/.ssh/authorized_keys; fi && '
    "echo __AUTHKEY_OK__"
)
_OK_MARK = "__AUTHKEY_OK__"


def _username(user: dict[str, Any] | None) -> str:
    if not user:
        return ""
    return str(user.get("user_id") or user.get("username") or user.get("id") or "")


async def _assert_can_configure_ssh(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    """创建者本人 / 平台超管 / 被分享者 才可写 key, 否则 403。

    user=None (内部调用) 放行。与开发机可见/可连的 code-editor 访问面一致。
    """
    if user is None:
        return
    username = _username(user)
    if username and username == str(row.get("creator_user_id") or ""):
        return
    if user.get("is_admin"):
        return
    from app.modules.sharing.visibility import shared_res_ids

    ws_id = str(row.get("workspace_id") or "")
    shared = await shared_res_ids(ws_id, username, "dev")
    if str(row.get("id")) in shared:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        t("devinstance.ssh_key_forbidden"),
    )


async def add_authorized_key_flow(
    k8s: K8sClient,
    id_: Any,
    public_key: str,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """写公钥到 authorized_keys。返回 {ok, message}。"""
    row = await _get_or_404(None, id_)
    await _assert_can_configure_ssh(row, user)

    ns = row["k8s_namespace"]
    ws_name = row["k8s_workspace_name"]
    try:
        pod = await k8s.get_pod_by_workspace(ns, ws_name)
    except K8sAPIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, t("devinstance.pod_query_failed", message=exc.message)
        ) from exc
    phase = (pod or {}).get("status", {}).get("phase") if pod else None
    if not pod or phase != "Running":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            t("devinstance.not_running_for_key"),
        )
    pod_name = pod["metadata"]["name"]

    out = await k8s.exec_in_pod(
        namespace=ns,
        pod_name=pod_name,
        container=_WORKSPACE_CONTAINER,
        command=["sh", "-c", _APPEND_KEY_SCRIPT, "_", public_key],
        timeout=10,
    )
    if out is None or _OK_MARK not in out:
        logger.warning(
            "dev_instance.authkey.exec_fail",
            id=str(row.get("id")),
            pod=pod_name,
            out=(out or "")[:300],
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            t("devinstance.ssh_key_write_failed"),
        )

    logger.info("dev_instance.authkey.ok", id=str(row.get("id")), pod=pod_name)
    return {"ok": True, "message": t("devinstance.ssh_key_written")}
