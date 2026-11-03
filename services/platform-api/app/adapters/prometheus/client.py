"""AMP (Amazon Managed Prometheus) HTTP API 异步客户端.

统一走 AMP + SigV4 签名 (本地 / 生产同源):
``https://aps-workspaces.<region>.amazonaws.com/workspaces/{ws_id}``

凭证: 本地用 aws cli profile, 生产用 Pod Identity / IRSA. 必须配
``AMP_WORKSPACE_ID``, 否则取数直接报错 (不再 fallback 自建 Prometheus).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session as BotocoreSession

from app.core.config import get_settings
from app.core.i18n import t
from app.core.logging import get_logger

logger = get_logger(__name__)

_AMP_SERVICE = "aps"


class PromAPIError(Exception):
    """Any failure calling the upstream Prometheus HTTP API."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"prom api http {status_code}: {body[:200]}")


def _base_url() -> str:
    """返 AMP query base path (含 /workspaces/<id> 前缀).

    AMP_WORKSPACE_ID 未配时直接报错 — 监控功能强依赖 AMP, 不再 fallback.
    """
    settings = get_settings()
    if not settings.amp_workspace_id:
        raise PromAPIError(
            500,
            t("prometheus.amp_workspace_missing"),
        )
    region = settings.aws_region or "us-west-2"
    return (
        f"https://aps-workspaces.{region}.amazonaws.com/"
        f"workspaces/{settings.amp_workspace_id}"
    )


def _sigv4_headers(method: str, url: str, body: str) -> dict[str, str]:
    """用 botocore 给 AMP 请求加 SigV4 头.

    自动从 AWS_PROFILE / IAM 角色拿 creds. boto3 内部用同 session,
    AWS_PROFILE / AWS_REGION 透传.
    """
    settings = get_settings()
    sess = BotocoreSession()
    if settings.aws_profile:
        sess.set_config_variable("profile", settings.aws_profile)
    if settings.aws_region:
        sess.set_config_variable("region", settings.aws_region)

    creds = sess.get_credentials()
    if creds is None:
        raise PromAPIError(401, "no AWS credentials available for AMP SigV4")

    req = AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            # 不要 zstd: AMP 会优先选它, 但 httpx 解压要 zstandard>=0.19 的
            # decompressor.eof, 而 sagemaker-hyperpod 硬 pin zstandard==0.15.2
            # → AttributeError (非 PromAPIError) 漏成 500, 图全空。
            "Accept-Encoding": "gzip, deflate",
        },
    )
    region = settings.aws_region or "us-west-2"
    SigV4Auth(creds.get_frozen_credentials(), _AMP_SERVICE, region).add_auth(req)
    return dict(req.headers)


async def _post(path: str, data: dict[str, str], timeout: float) -> dict[str, Any]:
    """统一 POST 到 AMP · 始终带 SigV4 签名."""
    url = f"{_base_url()}{path}"
    body = urlencode(data)
    headers = _sigv4_headers("POST", url, body)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, content=body, headers=headers)

    if resp.status_code >= 400:
        logger.warning(
            "prometheus.http_err",
            path=path,
            status=resp.status_code,
            body=resp.text[:200],
        )
        raise PromAPIError(resp.status_code, resp.text)
    return resp.json()


async def range_query(
    query: str, start: float, end: float, step: int
) -> dict:
    """POST /api/v1/query_range; returns parsed Prometheus JSON body."""
    return await _post(
        "/api/v1/query_range",
        {
            "query": query,
            "start": f"{start}",
            "end": f"{end}",
            "step": str(step),
        },
        timeout=20.0,
    )


async def instant_query(query: str, time: float | None = None) -> dict:
    """POST /api/v1/query; returns parsed Prometheus JSON body."""
    data: dict[str, str] = {"query": query}
    if time is not None:
        data["time"] = f"{time}"
    return await _post("/api/v1/query", data, timeout=10.0)
