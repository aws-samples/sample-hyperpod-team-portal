"""Workspace API 依赖注入工厂.

HyperPodClient 从 router 顶层抽出来, 方便 orchestration 层单测 mock。
"""

from __future__ import annotations

from app.adapters.k8s import K8sClient
from app.core.config import get_settings
from app.services.hyperpod_client import HyperPodClient


def get_hyperpod_client() -> HyperPodClient:
    """Workspace 级 AWS ComputeQuota 写打通共用的 HyperPod 客户端工厂."""
    settings = get_settings()
    return HyperPodClient(region=settings.aws_region, profile=settings.aws_profile)


def get_k8s_client() -> K8sClient:
    """Workspace 级 K8s 写客户端 (建 SA / Role / RoleBinding / PV / PVC)."""
    settings = get_settings()
    return K8sClient(context=settings.kube_context or None)
