"""LocaleMiddleware: http / websocket 设请求语言 + 响应头。"""
import pytest
from fastapi import FastAPI, Response, WebSocket
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import i18n
from app.core.locale_middleware import LocaleMiddleware


@pytest.fixture(autouse=True)
def _zh_cn_locale():
    """覆盖 conftest: 本文件测真实 DEFAULT (en-US)。"""
    yield


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(LocaleMiddleware)

    @app.get("/loc")
    async def loc() -> dict[str, str]:
        return {"locale": i18n.get_locale()}

    @app.get("/vary")
    async def vary() -> Response:
        return Response(content="x", headers={"Vary": "Origin"})

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text(i18n.get_locale())
        await websocket.close()

    return TestClient(app)


def test_http_default_is_en_us_with_headers():
    r = _client().get("/loc")
    assert r.json() == {"locale": "en-US"}
    assert r.headers["content-language"] == "en-US"
    assert "Accept-Language" in r.headers["vary"]


def test_http_accept_language_zh_cn():
    r = _client().get("/loc", headers={"Accept-Language": "zh-CN"})
    assert r.json() == {"locale": "zh-CN"}
    assert r.headers["content-language"] == "zh-CN"


def test_http_non_exact_zh_is_en_us():
    r = _client().get("/loc", headers={"Accept-Language": "zh-TW,zh;q=0.9"})
    assert r.json() == {"locale": "en-US"}


def test_query_lang_overrides_header():
    r = _client().get("/loc?lang=zh-CN", headers={"Accept-Language": "en-US"})
    assert r.json() == {"locale": "zh-CN"}


def test_websocket_uses_query_lang():
    with _client().websocket_connect("/ws?lang=zh-CN") as ws:
        assert ws.receive_text() == "zh-CN"


def test_websocket_default_en_us():
    with _client().websocket_connect("/ws") as ws:
        assert ws.receive_text() == "en-US"


def test_vary_merges_with_existing():
    r = _client().get("/vary")
    vary = r.headers["vary"]
    assert "Origin" in vary
    assert "Accept-Language" in vary


def test_locale_reset_after_request():
    r = _client().get("/loc", headers={"Accept-Language": "zh-CN"})
    assert r.json() == {"locale": "zh-CN"}
    assert i18n.get_locale() == "en-US"


def test_real_app_auth_401_carries_locale():
    # 不用 `with TestClient(...)`: 避免触发 lifespan (会 ping DDB)
    from app.main import app as real_app

    client = TestClient(real_app)
    r = client.get("/api/v1/workspaces", headers={"Accept-Language": "zh-CN"})
    assert r.status_code == 401
    assert r.headers["content-language"] == "zh-CN"
    assert "Accept-Language" in r.headers["vary"]

    r = client.get("/api/v1/workspaces")
    assert r.status_code == 401
    assert r.headers["content-language"] == "en-US"


def test_locale_visible_behind_basehttpmiddleware():
    """Locale 在外、BaseHTTPMiddleware 在内: async / sync 路由都读得到请求语言。"""

    class _Passthrough(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)

    app = FastAPI()
    app.add_middleware(_Passthrough)  # 先注册 = 内层
    app.add_middleware(LocaleMiddleware)  # 后注册 = 外层

    @app.get("/loc_async")
    async def loc_async() -> dict[str, str]:
        return {"locale": i18n.get_locale()}

    @app.get("/loc_sync")
    def loc_sync() -> dict[str, str]:
        return {"locale": i18n.get_locale()}

    c = TestClient(app)
    for path in ("/loc_async", "/loc_sync"):
        r = c.get(path, headers={"Accept-Language": "zh-CN"})
        assert r.json() == {"locale": "zh-CN"}, path
