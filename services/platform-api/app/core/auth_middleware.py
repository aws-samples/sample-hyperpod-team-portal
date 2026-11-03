"""全局 Auth Middleware · 默认全验, 白名单几个 endpoint 跳过.

设计目标:
- 防止"endpoint 漏写 Depends(get_current_user) 就裸奔"
- 兼容生产 ALB authenticate-cognito (注入 x-amzn-oidc-data) 和本地 PKCE Bearer 两条路径

层次:
1. middleware 验 token 真假 → 401 / 放行
2. endpoint Depends(get_current_user) 从 token 解出 user 对象 (按需)

不在 middleware 查 DDB:
- middleware 是 hot path, 每个请求都过, 不必要查 DDB
- 拿 user 对象的责任留给 Depends(get_current_user)
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

logger = logging.getLogger("platform_api.auth_middleware")


# 白名单 path · 这些 endpoint 不需要认证 (健康检查 / OAuth 公开配置 / API 文档)
# 用 set + startswith 双重匹配:
# - set 命中: 完全相等 (例 /healthz)
# - startswith 命中: 子路径 (例 /docs/swagger-ui-bundle.js, /api/v1/auth/...)
_WHITELIST_EXACT: frozenset[str] = frozenset(
    {
        "/healthz",
        "/api/openapi.json",  # OpenAPI 文档 (方案B: 挂在 /api 下)
        "/api/v1/openapi.json",
        "/api/v1/auth/config",  # OAuth 公开配置 (原靠 /api/v1/auth/ 前缀放行, 收紧为精确)
    }
)
_WHITELIST_PREFIXES: tuple[str, ...] = (
    "/api/docs",  # Swagger UI + 它的静态资源 (含 oauth2-redirect)
    "/api/redoc",  # ReDoc UI
    "/api/scalar",  # Scalar API Reference UI
    # 文档统一在 /api 下 (方案B); /docs 留给前端「产品文档」SPA, 不在此放行.
    # 不再整个 /api/v1/auth/ 前缀放行, 防新端点 (如 api-token) 裸奔
)


def _is_whitelisted(path: str) -> bool:
    if path in _WHITELIST_EXACT:
        return True
    return any(path.startswith(p) for p in _WHITELIST_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """全局 auth 验签 middleware.

    执行顺序:
    1. 白名单 path → 直接放行
    2. x-amzn-oidc-data header (生产 ALB 场景) → 验 ALB 签名
    3. Authorization: Bearer (本地 PKCE / 脚本场景) → 验 Cognito / API Token
    4. 都没 → 401

    middleware 只决定"通不通过", 不解 user 对象.
    需要 user 对象的 endpoint 仍然用 Depends(get_current_user).
    """

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        # BaseHTTPMiddleware 只支持 http scope, 对 websocket 会破坏握手 (返 403)。
        # WS 直接透传给下层 app, 鉴权由 websocket handler 自己做 (验 query/cookie token)。
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[JSONResponse]],
    ) -> JSONResponse:
        path = request.url.path

        # 1. 白名单
        if _is_whitelisted(path):
            return await call_next(request)

        settings = get_settings()

        # 验 token (ALB header / Bearer Cognito / Bearer API Token)
        try:
            await self._verify_request(request, settings)
        except _AuthFailure as exc:
            logger.warning("[auth_mw] %s %s · %s", request.method, path, exc.detail)
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
            )

        return await call_next(request)

    @staticmethod
    async def _verify_request(request: Request, settings) -> None:  # type: ignore[no-untyped-def]
        """验签的具体逻辑. 失败抛 _AuthFailure (用我们自己的异常,
        避免 FastAPI HTTPException 在 middleware 层被双重处理)."""

        # 路径 1 · ALB 注入 (生产浏览器场景)
        alb_token = request.headers.get("x-amzn-oidc-data")
        if alb_token:
            from app.core.alb_jwt import verify_alb_oidc_data
            try:
                verify_alb_oidc_data(alb_token, settings)
            except Exception as exc:  # 已在 alb_jwt 内 logger 详细日志
                raise _AuthFailure(401, f"ALB token invalid: {exc}")
            return

        # 路径 2 · Bearer (本地 PKCE / 脚本场景)
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            if not token:
                raise _AuthFailure(401, "empty Bearer token")
            # 2a · API Token (hypd_ 前缀) — 脚本 headless 场景
            from app.core.token_util import TOKEN_PREFIX
            if token.startswith(TOKEN_PREFIX):
                await _verify_api_token(token)
                return
            # 2b · Cognito JWT (浏览器 PKCE)
            from app.core.cognito_jwt import verify_cognito_id_token
            try:
                verify_cognito_id_token(token, settings)
            except Exception as exc:
                raise _AuthFailure(401, f"Cognito token invalid: {exc}")
            return

        # 路径 3 · query string ?access_token= (浏览器无法设 Authorization header).
        # 适用:
        #   - /logs/stream (SSE / EventSource)
        #   - /logs/history/download (浏览器直接打开链接触发文件下载, 同样无 header)
        #   - /dev-instances/{id}/proxy/* (本地 mac 浏览器开 JupyterLab/Code-Editor,
        #     需要 settings.enable_dev_proxy_query_token=True; 生产 ALB
        #     authenticate-cognito 后浏览器自带 ELB session cookie, 此项保持
        #     False)
        path_str = request.url.path
        is_logs_stream = path_str.endswith(
            ("/logs/stream", "/logs/history/download")
        )
        is_proxy = "/dev-instances/" in path_str and "/proxy/" in path_str
        allow_query = is_logs_stream or (
            is_proxy and getattr(settings, "enable_dev_proxy_query_token", False)
        )
        if allow_query:
            qtoken = request.query_params.get("access_token", "").strip()
            if qtoken:
                from app.core.cognito_jwt import verify_cognito_id_token
                try:
                    verify_cognito_id_token(qtoken, settings)
                except Exception as exc:
                    raise _AuthFailure(401, f"Cognito query token invalid: {exc}")
                return

        # 路径 4 · proxy 路径的 cookie token.
        # Code Editor/JupyterLab 首页 (导航请求) 带 ?access_token=, proxy handler
        # 验过后 Set-Cookie; 之后首页引用的 css/js/png 等子资源是浏览器自动发起,
        # URL 不带 query token, 靠这个 cookie 认证 (cookie 同源自动带)。
        if is_proxy:
            ctoken = request.cookies.get("dev_proxy_token", "").strip()
            if ctoken:
                from app.core.cognito_jwt import verify_cognito_id_token
                try:
                    verify_cognito_id_token(ctoken, settings)
                except Exception as exc:
                    raise _AuthFailure(401, f"Cognito cookie token invalid: {exc}")
                return

        # 啥都没
        raise _AuthFailure(401, "missing authentication")


async def _verify_api_token(token: str) -> None:
    """验 API Token: hash 反查 GSI + 未过期. 失败抛 _AuthFailure(401).

    只判'有效性', 不解 user (解 user 是 get_current_user 的事).
    """
    from app.core.token_util import hash_token
    from app.repositories import api_tokens as api_tokens_repo

    rec = await api_tokens_repo.get_by_hash(hash_token(token))
    if rec is None:
        raise _AuthFailure(401, "API token invalid or revoked")
    if api_tokens_repo.is_expired(rec.get("expires_at")):
        raise _AuthFailure(401, "API token expired")


class _AuthFailure(Exception):
    """middleware 内部用 · 不抛 FastAPI HTTPException 是为了避免与 exception_handler 互相嵌套."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
