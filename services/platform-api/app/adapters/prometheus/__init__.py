"""adapters/prometheus · AMP (Amazon Managed Prometheus) HTTP 客户端.

本子包封装对 AMP 的 HTTP 调用 (SigV4 签名), 供 monitoring 模块使用。
本地 / 生产同源, 统一走 AMP, 由 observability add-on remote-write 喂数据。

凭证:
    - 本地: aws cli profile (AWS_PROFILE / 默认凭证链)
    - 生产: Pod Identity / IRSA

配置:
    必须设 ``AMP_WORKSPACE_ID``; 未配时取数抛 PromAPIError(500)。

入口符号:
    ``instant_query`` / ``range_query``: 返回 Prometheus JSON body (passthrough)
    ``PromAPIError``: 上游 HTTP 错误统一异常
"""

from __future__ import annotations

from .client import PromAPIError, instant_query, range_query

__all__ = ["PromAPIError", "instant_query", "range_query"]
