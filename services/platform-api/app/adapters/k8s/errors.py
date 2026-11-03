"""K8s 适配层统一异常.

职责:
    定义 adapters/k8s/* 内所有 K8s API 调用失败时抛出的统一异常类型,
    下游 (routers / services) 捕获 K8sAPIError 即可处理所有 K8s 侧错误.
"""

from __future__ import annotations


class K8sAPIError(Exception):
    """K8s API 调用失败的统一异常.

    Attributes:
        code: 错误码, 形如 "ApiException.404" 或 "Unknown"
        message: 人类可读的错误描述
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
