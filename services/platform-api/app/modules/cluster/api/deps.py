"""FastAPI dependencies for cluster 模块

独立封装 HyperPodClient / K8sClient 的构造逻辑，便于测试 override。
"""

from __future__ import annotations

from app.adapters.k8s import K8sClient
from app.core.config import get_settings
from app.services.hyperpod_client import HyperPodClient


def get_hyperpod_client() -> HyperPodClient:
    """每请求新建 HyperPod 客户端（aioboto3 session 轻量，不复用）"""
    settings = get_settings()
    return HyperPodClient(region=settings.aws_region, profile=settings.aws_profile)


def get_k8s_client() -> K8sClient:
    """每请求新建 K8s 客户端（kubernetes-asyncio）.

    settings.kube_context 为空 → K8sClient 用 kubeconfig current-context.
    """
    settings = get_settings()
    return K8sClient(context=settings.kube_context or None)
