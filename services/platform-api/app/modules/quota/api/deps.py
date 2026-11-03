"""Quota API dependencies.

当前只有 HyperPodClient 一个依赖. Kueue 侧在 orchestration/usage_sync.py
内部直接 new KueueClient (无连接池), 不走 DI.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.services.hyperpod_client import HyperPodClient


def get_hyperpod_client() -> HyperPodClient:
    """Dependency: 每请求 new 一个 HyperPod async client."""
    settings = get_settings()
    return HyperPodClient(region=settings.aws_region, profile=settings.aws_profile)
