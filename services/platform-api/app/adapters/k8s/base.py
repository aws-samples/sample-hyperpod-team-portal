"""K8s 客户端基类 + 跨 kind 共享工具.

职责:
    - K8sClientBase: 封装 kubernetes-asyncio kubeconfig 加载, 供各 kind mixin 复用
    - _to_primitive: kubernetes-asyncio model 对象 -> 纯 dict 的递归转换

本文件不绑定任何 CR kind, 所有具体 CR / 内建资源操作放在 adapters/k8s/<kind>.py.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from kubernetes_asyncio import config as k8s_config

log = logging.getLogger("k8s_base")


def _to_primitive(o: Any) -> Any:
    """把 kubernetes-asyncio 的 model 对象转 dict,递归走 to_dict 再回纯 Python."""
    if hasattr(o, "to_dict"):
        return o.to_dict()
    return o


# Process-level kubeconfig load cache · TTL 5 min.
# EKS aws-iam-authenticator exec token 15 min 过期, 提前 5 min 重 load
# 避免 401 Unauthorized.
_LOAD_LOCK: asyncio.Lock | None = None
_LOADED_AT: dict[str, float] = {}  # cache_key → epoch seconds 加载时刻
_TTL_SECONDS = 60  # 1 min · EKS exec token cache 但保持新鲜


def _get_lock() -> asyncio.Lock:
    global _LOAD_LOCK
    if _LOAD_LOCK is None:
        _LOAD_LOCK = asyncio.Lock()
    return _LOAD_LOCK


def reset_config_cache(context: str | None = None) -> None:
    """清除指定 context 的 kubeconfig 加载缓存, 强制下次 _load_config 真正 reload。
    用于 401 (token 过期) 后: TTL 缓存可能挡住 60s 内的 reload, 戳掉它确保拿新 token。
    """
    _LOADED_AT.pop(context or "__current__", None)


class K8sClientBase:
    """Kubernetes 异步客户端基类.

    子类 (或 mixin) 通过 ``await self._load_config()`` 加载 kubeconfig,
    然后在 ``async with ApiClient() as api`` 里发起具体请求.

    context=None 时用 kubeconfig 当前 context (适合本地开发, aws eks
    update-kubeconfig 写过的就用那个).
    """

    def __init__(self, context: str | None = None) -> None:
        # context=None / "" → load_kube_config 用 kubeconfig 当前 current-context.
        # 显式传非空 context 则锁定 (跨集群 / 测试用).
        self._context = context or None

    async def _load_config(self) -> None:
        cache_key = self._context or "__current__"
        now = time.time()
        loaded_at = _LOADED_AT.get(cache_key, 0)
        if now - loaded_at < _TTL_SECONDS:
            log.debug("k8s.load_skip cache_age=%.0fs", now - loaded_at)
            return
        async with _get_lock():
            if time.time() - _LOADED_AT.get(cache_key, 0) < _TTL_SECONDS:
                log.debug("k8s.load_skip(lock)")
                return
            log.debug("k8s.load_kube_config start ctx=%s", self._context)
            if self._context:
                await k8s_config.load_kube_config(context=self._context)
            else:
                await k8s_config.load_kube_config()
            _LOADED_AT[cache_key] = time.time()
            # 不打 token 任何字符 (凭据泄漏); tok_len 仅用于"是否拿到 token"诊断。
            from kubernetes_asyncio.client import Configuration
            c = Configuration.get_default_copy()
            tok_len = len((c.api_key or {}).get("BearerToken", ""))
            log.debug("k8s.load_kube_config done host=%s tok_len=%d", c.host, tok_len)
