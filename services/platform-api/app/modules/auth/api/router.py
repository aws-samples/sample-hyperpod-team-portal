"""Auth 模块 router.

当前提供:
    GET /auth/config — 给前端 SPA PKCE flow 启动用 (无需认证, 返公开配置)

未来 Phase 3+ 会补:
    POST /auth/callback — 后端 OIDC code exchange (如果不走纯前端 PKCE)
    POST /auth/logout   — 清 Cognito session

安全考量:
    - 这个 endpoint 故意无认证, 因为前端 SPA 拿不到配置就没法跳登录
    - 返的所有字段都是 OAuth public client 设计上公开的 (不含 client_secret)
    - 该端点的公开配置清单以本文件的响应模型为准
"""
from __future__ import annotations

from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.modules.auth.api.schemas import AuthConfigResponse

auth_router = APIRouter(tags=["auth"])


@auth_router.get(
    "/auth/config",
    response_model=AuthConfigResponse,
    summary="Get OIDC public config for SPA PKCE flow",
    description=(
        "返前端启动 PKCE flow 需要的 Cognito 公开配置. "
        "无需认证. 不包含任何 secret. 浏览器可缓存 5 分钟."
    ),
)
async def get_auth_config(response: Response) -> AuthConfigResponse:
    s = get_settings()

    # 推导 issuer (如果 Settings 里没显式给, 从 region + user_pool_id 拼)
    if s.cognito_user_pool_id:
        cognito_issuer = (
            f"https://cognito-idp.{s.cognito_region}.amazonaws.com/{s.cognito_user_pool_id}"
        )
    else:
        cognito_issuer = ""

    # 浏览器可缓存 (内容很少变, 配置改动 重启后端即生效, 5 分钟够)
    response.headers["Cache-Control"] = "public, max-age=300"

    return AuthConfigResponse(
        cognito_issuer=cognito_issuer,
        cognito_client_id=s.cognito_client_id,
        cognito_domain=s.cognito_domain,
        local_callback_url=s.local_callback_url,
    )
