"""请求语言中间件 (纯 ASGI, 覆盖 http + websocket)。

解析 ?lang= / Accept-Language (规则见 app.core.i18n.resolve_locale) → 写当前请求的 ContextVar,
深层业务代码抛错时直接 t(), 不用一路传 request。http 响应补 Vary: Accept-Language 与
Content-Language。不用 BaseHTTPMiddleware: 它不处理 websocket (见 AuthMiddleware.__call__)。

注意: 未捕获异常的 500 由最外层 ServerErrorMiddleware 生成, 此时语言已复位为 DEFAULT;
将来若加全局 exception_handler(Exception) 且其中调用 t(), 需注意这一点。
"""

from __future__ import annotations

from urllib.parse import parse_qs

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.i18n import reset_locale, resolve_locale, set_locale


class LocaleMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        accept = None
        for name, value in scope.get("headers") or []:
            if name == b"accept-language":
                accept = value.decode("latin-1")
                break
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        locale = resolve_locale(accept, (query.get("lang") or [None])[0])

        token = set_locale(locale)
        try:
            if scope["type"] == "websocket":
                await self.app(scope, receive, send)
                return

            async def send_with_locale_headers(message: Message) -> None:
                if message["type"] == "http.response.start":
                    message.setdefault("headers", [])
                    headers = MutableHeaders(scope=message)
                    headers.add_vary_header("Accept-Language")
                    headers["Content-Language"] = locale
                await send(message)

            await self.app(scope, receive, send_with_locale_headers)
        finally:
            reset_locale(token)
