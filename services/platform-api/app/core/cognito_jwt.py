"""Cognito ID token 验签 (M2 接 Cognito UserPool 时用).

为什么不放 modules/auth/:
    auth 模块按资产导向是"业务 auth flow", 而 token 验签是 platform 横切关注,
    放在 core/ 里被 security.py 调用更合适.

外部依赖:
    - python-jose (已在 pyproject)
    - httpx (拉 JWKS)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from fastapi import HTTPException
from jose import jwk, jwt
from jose.exceptions import JWKError, JWTError

from app.core.config import Settings

logger = logging.getLogger("platform_api.cognito_jwt")


@dataclass
class CognitoClaims:
    """Cognito ID token 验签后解出的关键字段."""

    sub: str  # Cognito federated user UUID (验签内部用, 业务层用 username)
    email: str
    name: str
    cognito_username: str  # cognito:username (Cognito 内部, 形如 idp_<NameID>)
    username: str  # IdC username (来自 identities[0].userId · 业务层主 ID)


# Cognito JWKS 缓存 5 分钟 (防 rate limit + 支持 key 轮转)
_jwks_cache: dict | None = None
_jwks_cache_ts: float = 0.0
_JWKS_TTL = 300


def verify_cognito_id_token(token: str, settings: Settings) -> CognitoClaims:
    """验 Cognito UserPool 签的 ID token, 返 claims.

    必须验:
    - 签名 (RS256, JWKS)
    - iss = https://cognito-idp.{region}.amazonaws.com/{user_pool_id}
    - aud = settings.cognito_client_id
    - exp 没过期 (jose 默认验)
    - token_use = 'id' (区分 id_token vs access_token)
    - at_hash 不验 (authorization code flow 不需要, jose 默认验需关)
    """
    issuer = _build_issuer(settings)
    jwks_url = f"{issuer}/.well-known/jwks.json"

    if not settings.cognito_user_pool_id or not settings.cognito_client_id:
        raise HTTPException(
            503,
            "Cognito not configured (set COGNITO_USER_POOL_ID + COGNITO_CLIENT_ID)",
        )

    # 解 unverified claims 给 debug 日志用
    try:
        unverified = jwt.get_unverified_claims(token)
        logger.info(
            "[cognito_jwt] verifying: iss=%s aud=%s token_use=%s sub=%s email=%s exp=%s",
            unverified.get("iss"), unverified.get("aud"), unverified.get("token_use"),
            unverified.get("sub"), unverified.get("email"), unverified.get("exp"),
        )
    except JWTError as exc:
        logger.error("[cognito_jwt] cannot parse token claims: %s", exc)

    try:
        headers = jwt.get_unverified_headers(token)
    except JWTError as exc:
        raise HTTPException(401, f"invalid Cognito token header: {exc}")

    kid = headers.get("kid")
    if not kid:
        raise HTTPException(401, "Cognito token missing kid")

    jwks = _get_jwks(jwks_url)
    key_dict = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not key_dict:
        # key 可能刚轮转, 强制刷一次再试
        jwks = _get_jwks(jwks_url, force=True)
        key_dict = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key_dict:
            available = [k.get("kid") for k in jwks.get("keys", [])]
            logger.error("[cognito_jwt] kid %s not in JWKS, available: %s", kid, available)
            raise HTTPException(401, f"unknown Cognito kid {kid}")

    try:
        public_key = jwk.construct(key_dict)
    except JWKError as exc:
        raise HTTPException(503, f"failed to construct Cognito public key: {exc}")

    try:
        claims = jwt.decode(
            token,
            public_key.to_pem().decode(),
            algorithms=[key_dict.get("alg", "RS256")],
            issuer=issuer,
            audience=settings.cognito_client_id,
            options={
                "verify_aud": True,
                # at_hash 仅在 implicit/hybrid flow 需验, code flow 后端没 access_token
                # python-jose 默认会强制验, 不关掉所有 Cognito ID token 都过不了
                "verify_at_hash": False,
            },
        )
    except JWTError as exc:
        logger.error(
            "[cognito_jwt] verify failed: %s · expected_iss=%r aud=%r",
            exc, issuer, settings.cognito_client_id,
        )
        raise HTTPException(401, f"Cognito token invalid: {exc}")

    token_use = claims.get("token_use")
    if token_use and token_use != "id":
        raise HTTPException(
            401,
            f"expected Cognito id_token but got token_use={token_use}",
        )

    # 从 identities 数组拿 IdC username (SAML NameID)
    # IdC SAML application 配置 Subject = ${user:subject}, 在 IdC native user
    # 上实际值 = IdC username. token claim "identities" 是 Cognito 把 SAML NameID
    # 透传到 ID token 的标准字段.
    identities = claims.get("identities") or []
    username = ""
    if identities and isinstance(identities, list):
        username = (identities[0] or {}).get("userId", "") if identities[0] else ""

    return CognitoClaims(
        sub=claims.get("sub", ""),
        email=claims.get("email", ""),
        name=claims.get("name") or claims.get("cognito:username", ""),
        cognito_username=claims.get("cognito:username", ""),
        username=username,
    )


def _build_issuer(settings: Settings) -> str:
    return (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}"
    )


def _get_jwks(jwks_url: str, *, force: bool = False) -> dict:
    """JWKS 缓存 5 分钟."""
    global _jwks_cache, _jwks_cache_ts
    now = time.time()
    if not force and _jwks_cache and (now - _jwks_cache_ts) < _JWKS_TTL:
        return _jwks_cache

    try:
        resp = httpx.get(jwks_url, timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"failed to fetch Cognito JWKS: {exc}")

    _jwks_cache = resp.json()
    _jwks_cache_ts = now
    return _jwks_cache


# 测试用: 重置 JWKS 缓存
def _reset_jwks_cache() -> None:
    global _jwks_cache, _jwks_cache_ts
    _jwks_cache = None
    _jwks_cache_ts = 0.0
