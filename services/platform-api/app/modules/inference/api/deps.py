"""FastAPI dependency 工厂 · inference 专用 (镜像 training/api/deps.py)."""

from __future__ import annotations

from app.core.config import get_settings
from app.services.k8s_client import K8sClient


def get_k8s_client() -> K8sClient:
    """K8s async client 实例 · FastAPI Depends 入口."""
    return K8sClient(context=get_settings().kube_context or None)
