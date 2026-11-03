"""Auth 模块 Pydantic schemas.

这是前端 PKCE flow 启动器拿配置用的形状, 必须和
frontend/src/features/auth/login.ts 的 AuthConfig interface 字段对齐.
改动这个 schema 必须跑 make api-sync.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthConfigResponse(BaseModel):
    """前端 OIDC PKCE flow 用的 Cognito 配置.

    所有字段都是公开信息 (OAuth 2.0 SPA / public client 设计哲学):
    - issuer / client_id / domain 在 Cognito 跳转 URL 上必然出现

    真敏感的 (client_secret / AWS keys / DB 密码) 永远不放这里.
    """

    model_config = ConfigDict(extra="forbid")

    cognito_issuer: str = Field(
        ...,
        description="Cognito UserPool issuer URL (= https://cognito-idp.{region}.amazonaws.com/{user_pool_id})",
    )
    cognito_client_id: str = Field(..., description="Cognito App Client ID")
    cognito_domain: str = Field(
        ...,
        description="Cognito Hosted UI 域名, 不带 https:// (例 xxx.auth.ap-south-1.amazoncognito.com)",
    )
    local_callback_url: str = Field(
        ...,
        description="前端 PKCE flow callback URL (本地 dev 用)",
    )
