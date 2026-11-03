"""Kubernetes async client · 向后兼容 shim.

实现已迁移到 ``app.adapters.k8s`` (按 CR kind 分文件).
本文件仅做 re-export, 保持旧 import path 可用::

    from app.services.k8s_client import K8sClient, K8sAPIError

新代码建议直接 import from app.adapters.k8s.
"""

from __future__ import annotations

from app.adapters.k8s import (
    K8sAPIError,
    K8sClient,
    K8sClientBase,
    _to_primitive,
)

__all__ = [
    "K8sAPIError",
    "K8sClient",
    "K8sClientBase",
    "_to_primitive",
]
