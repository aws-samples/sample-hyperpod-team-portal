"""Secret HTTP routes · 每人管自己的 key-value 凭证 (B2 每人一把)。

secret 名平台自动派生 (用户无感), 只暴露 key-value 增删查; value 建后不回显。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.modules.secret.api.schemas import SecretKeyPut, SecretView
from app.modules.secret.orchestration import tokens as secret_svc
from app.modules.training.api.deps import get_k8s_client
from app.services.k8s_client import K8sClient

secret_router = APIRouter(tags=["secret"])


@secret_router.get(
    "/workspaces/{ws_id}/secrets",
    response_model=SecretView,
    summary="查看本人 Secret 的 key 列表",
    description=(
        "返当前用户在本 ws 下 Secret 的 key 清单 (不含 value).\n\n"
        "- 每人一把 Secret: 名平台自动派生 `<owner>-secrets`, 落在该 ws 的 K8s namespace, 用户无感\n"
        "- 用于**个人凭证**面板展示已配置了哪些 key (HF_TOKEN / WANDB_API_KEY / 自定义…), value 从不回显\n"
        "- Secret 尚未创建过 → 返 `{\"keys\": []}` (不 404)\n\n"
        "**权限**: ws 成员 (平台超管豁免). 只能看自己的 (secret 名派生自登录身份)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管"},
        404: {"description": "workspace 不存在"},
        500: {"description": "K8s API 调用失败"},
    },
)
async def get_secret_view(
    ws_id: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SecretView:
    return await secret_svc.get_view(k8s, ws_id, current_user)


@secret_router.put(
    "/workspaces/{ws_id}/secrets/keys",
    response_model=SecretView,
    summary="写入/更新一个 key-value",
    description=(
        "为当前用户在本 ws 的 Secret 中加 / 改一个键值对.\n\n"
        "- 同 key 覆盖 (无版本历史); 走 read-modify-write, 不影响同 Secret 其他 key\n"
        "- 首次写入时自动创建底层 K8s Secret (Opaque, 每人一把, 打 owner annotation)\n"
        "- value 只进 K8s Secret 不落 DDB; 响应只回 key 列表, value 永不回显\n\n"
        "**权限**: ws 成员 (平台超管豁免). 只能写自己的那把."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管"},
        404: {"description": "workspace 不存在"},
        422: {"description": "key 空 / 超 253 字符; value 空 / 超 8192 字符"},
        500: {"description": "K8s API 调用失败 (如 namespace 不存在 / 无权限)"},
    },
)
async def put_secret_key(
    ws_id: str,
    payload: SecretKeyPut,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SecretView:
    return await secret_svc.put_key(k8s, ws_id, payload, current_user)


@secret_router.delete(
    "/workspaces/{ws_id}/secrets/keys/{key}",
    response_model=SecretView,
    summary="删除本人的一个 key",
    description=(
        "从当前用户在本 ws 的 Secret 中移除指定 key. 返最新 key 列表 (SecretView).\n\n"
        "**权限**: ws 成员 (平台超管豁免). "
        "**幂等**: 删不存在的 key 返当前视图; Secret 整个不存在返 `{\"keys\": []}` (均不 404)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非 ws 成员且非超管"},
        404: {"description": "workspace 不存在"},
        500: {"description": "K8s API 调用失败"},
    },
)
async def delete_secret_key(
    ws_id: str,
    key: str,
    k8s: K8sClient = Depends(get_k8s_client),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SecretView:
    return await secret_svc.delete_key(k8s, ws_id, key, current_user)
