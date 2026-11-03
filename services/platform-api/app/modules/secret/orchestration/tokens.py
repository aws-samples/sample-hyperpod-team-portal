"""通用 Secret 编排 (B2 每人一把): 权限校验 + 管本人 secret 的 key-value。

每人一把固定 k8s Secret, 名平台自动派生 <owner>-secrets (用户无感, 只管 key-value)。
权限: 只能管自己的 (名派生自登录身份); 非 ws 成员 403。
存储: value 只进 ws namespace 的 k8s Secret, 不落 DDB。
通用凭证无法预验有效性 (不同 的 github token), 只校验 key 格式。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import t
from app.core.naming import sanitize_dns_label
from app.modules.secret.api.schemas import SecretKeyPut, SecretView
from app.modules.workspace import crud as ws_crud
from app.services.k8s_client import K8sClient

_FALLBACK_K8S_NS = "default"
_ANN_OWNER = "platform.hyperpod.io/owner"


def _username(user: dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("username") or user.get("id"))


def secret_name_for(user: dict[str, Any]) -> str:
    """本人固定 Secret 名: <owner>-secrets (用户无感, 训练 secretKeyRef 也用它)。"""
    return f"{sanitize_dns_label(_username(user), fallback='user')}-secrets"


async def _require_ws_member(ws_id: str, user: dict[str, Any]) -> None:
    """校验 user 是该 ws 成员 (平台超管豁免)。非成员抛 403。"""
    if user.get("is_admin"):
        return
    m = await ws_crud.get_membership(None, ws_id, _username(user))
    if not m:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            t("secret.not_ws_member"),
        )


async def _resolve_ns(ws_id: str) -> str:
    ws = await ws_crud.get_workspace(None, ws_id)
    if ws is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"workspace not found: {ws_id}"
        )
    return ws.get("namespace") or _FALLBACK_K8S_NS


async def put_key(
    k8s: K8sClient, ws_id: str, payload: SecretKeyPut, user: dict[str, Any]
) -> SecretView:
    """加/改本人 secret 里一个 key-value (secret 不存在则建)。"""
    await _require_ws_member(ws_id, user)
    ns = await _resolve_ns(ws_id)
    keys = await k8s.put_secret_key(
        ns,
        secret_name_for(user),
        payload.key.strip(),
        payload.value,
        annotations={_ANN_OWNER: _username(user)},
    )
    return SecretView(keys=keys)


async def get_view(
    k8s: K8sClient, ws_id: str, user: dict[str, Any]
) -> SecretView:
    """看本人 secret 的 key 名 (不含 value)。"""
    await _require_ws_member(ws_id, user)
    ns = await _resolve_ns(ws_id)
    keys = await k8s.get_secret_keys(ns, secret_name_for(user))
    return SecretView(keys=keys)


async def delete_key(
    k8s: K8sClient, ws_id: str, key: str, user: dict[str, Any]
) -> SecretView:
    """删本人 secret 里一个 key。"""
    await _require_ws_member(ws_id, user)
    ns = await _resolve_ns(ws_id)
    keys = await k8s.delete_secret_key(ns, secret_name_for(user), key)
    return SecretView(keys=keys)
