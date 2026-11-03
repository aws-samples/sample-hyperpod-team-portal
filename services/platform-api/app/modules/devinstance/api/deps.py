"""FastAPI dependency injection.

把 K8sClient 实例化留在这层 (测试可 overrides_dependencies 替 mock).
"""

from __future__ import annotations

from app.adapters.k8s import K8sClient
from app.core.config import get_settings


def get_k8s_client() -> K8sClient:
    """每个请求一个 K8sClient 实例 (无状态, 内部复用 kubeconfig)."""
    return K8sClient(context=get_settings().kube_context or None)
