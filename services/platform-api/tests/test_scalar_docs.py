"""Scalar API Reference · 集成守门测试 (方案B: 文档挂在 /api 前缀下).

验证:
1. /api/scalar 路由存在且无需认证即可访问 (在 AuthMiddleware 白名单内)
2. 返回的 HTML 引用了 /api/openapi.json (Scalar 消费的 OpenAPI 文档)
3. /api/openapi.json 本身无需认证可访问 (Scalar 前端 fetch 它)
4. 受保护端点 (非白名单) 仍然返回 401 — 确认放行没放过头
5. 旧的根路径 /scalar、/openapi.json 不再存在 (已统一迁到 /api)
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_scalar_route_reachable_without_auth() -> None:
    client = _client()
    resp = client.get("/api/scalar")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")


def test_scalar_html_references_openapi_document() -> None:
    client = _client()
    body = client.get("/api/scalar").text
    # Scalar HTML 内嵌它要加载的 OpenAPI 文档 URL (/api 前缀下)
    assert "/api/openapi.json" in body
    # 加载 Scalar 前端 bundle 的 script (默认 CDN)
    assert "@scalar/api-reference" in body


def test_openapi_json_reachable_without_auth() -> None:
    client = _client()
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200, resp.text
    schema = resp.json()
    assert schema.get("openapi")
    assert schema.get("paths")


def test_protected_endpoint_still_requires_auth() -> None:
    """白名单放行不能误伤受保护端点: 随便挑一个 /api/v1 端点应 401."""
    client = _client()
    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 401, (
        f"受保护端点未被 AuthMiddleware 拦截 (status={resp.status_code}); "
        "白名单可能放行过头"
    )


def test_legacy_root_paths_gone() -> None:
    """旧根路径已迁到 /api 前缀, 根路径不应再返回文档.

    AuthMiddleware 对非白名单路径先返 401; 根 /scalar /openapi.json 已不在白名单,
    所以这里期望 401 (而非 200 文档). 这能防止回退到旧路径而无人察觉.
    """
    client = _client()
    assert client.get("/scalar").status_code == 401
    assert client.get("/openapi.json").status_code == 401
