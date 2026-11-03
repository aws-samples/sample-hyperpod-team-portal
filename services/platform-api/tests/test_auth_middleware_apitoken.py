"""中间件白名单收紧 + API Token 分流判断测试."""
from app.core.auth_middleware import _is_whitelisted


def test_auth_config_still_whitelisted():
    assert _is_whitelisted("/api/v1/auth/config") is True


def test_auth_other_endpoints_not_whitelisted():
    # 收紧后: /auth/ 下非 config 的端点不再免认证
    assert _is_whitelisted("/api/v1/auth/api-token") is False
    assert _is_whitelisted("/api/v1/auth/anything") is False


def test_healthz_and_docs_still_whitelisted():
    assert _is_whitelisted("/healthz") is True
    # 文档统一在 /api 下 (方案B)
    assert _is_whitelisted("/api/docs") is True
    assert _is_whitelisted("/api/docs/swagger-ui.css") is True
    assert _is_whitelisted("/api/redoc") is True
    assert _is_whitelisted("/api/scalar") is True
    assert _is_whitelisted("/api/openapi.json") is True
    # /docs 现在归前端「产品文档」SPA, 不再由后端放行
    assert _is_whitelisted("/docs") is False


def test_business_endpoint_not_whitelisted():
    assert _is_whitelisted("/api/v1/users/me/api-token") is False
    assert _is_whitelisted("/api/v1/training/jobs") is False
