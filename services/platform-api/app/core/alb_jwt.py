"""ALB authenticate-cognito 注入的 x-amzn-oidc-data JWT 验签.

部署 Fargate 走 ALB 后:
- ALB 完成 OIDC 流程, 自己签一份 ES256 JWT 注入到 x-amzn-oidc-data header
- header 内容是 ALB 私钥签的, 公钥在 region 固定 endpoint:
    https://public-keys.auth.elb.{region}.amazonaws.com/{kid}

后端必须验 ALB 签名, 不能盲信 header:
- 攻击者可能绕开 ALB 直接打 task 内网 IP (SG 配错 / VPC 横向移动 / 容器逃逸)
- 自己塞个假 x-amzn-oidc-data header 进来
- 后端用 ALB region 公钥验签 + 验 signer claim == 我们 ALB ARN

本地开发不会进这条路径 (没 ALB 也没人注入这 header), middleware 自动 fallback Bearer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import Settings

logger = logging.getLogger("platform_api.alb_jwt")


@dataclass
class ALBClaims:
    """ALB 注入的 JWT 解出的 claims."""

    sub: str
    email: str
    name: str
    signer: str  # 签发的 ALB ARN, 必须和我们配置的 ALB 匹配


# ALB 公钥缓存 · kid 滚动期 ~ 数月, 缓存到内存即可
_alb_key_cache: dict[str, str] = {}


def verify_alb_oidc_data(token: str, settings: Settings) -> ALBClaims:
    """验 ALB 注入的 x-amzn-oidc-data.

    必须验:
    - 签名 (ES256, 用 ALB region 公钥)
    - exp 没过期 (jose 默认验)
    - signer = settings.alb_arn (防别的 ALB 的 token 拿来用)

    ALB JWT 没有 aud claim, options 里要关 verify_aud.
    """
    if not settings.alb_arn:
        # 本地或未配 ALB ARN 的部署 — middleware 不应路由到这条路径
        # 但万一被路由到 (运维错配), 给一个明确错误而不是默默通过
        raise RuntimeError("ALB_ARN not configured but x-amzn-oidc-data header present")

    try:
        headers = jwt.get_unverified_headers(token)
    except JWTError as exc:
        raise ValueError(f"invalid ALB token header: {exc}")

    kid = headers.get("kid")
    if not kid:
        raise ValueError("ALB token missing kid")

    public_key_pem = _get_alb_public_key(kid, settings.aws_region)

    try:
        claims = jwt.decode(
            token,
            public_key_pem,
            algorithms=["ES256"],
            options={"verify_aud": False},  # ALB 注入的 JWT 没有 aud
        )
    except JWTError as exc:
        logger.error(
            "[alb_jwt] verify failed: %s · expected_alb_arn=%r",
            exc, settings.alb_arn,
        )
        raise ValueError(f"ALB token signature invalid: {exc}")

    # signer = 签发这个 token 的 ALB ARN, 防别的 ALB token 被拿来用
    signer = claims.get("signer", "")
    if signer != settings.alb_arn:
        raise ValueError(
            f"ALB token signer mismatch: expected {settings.alb_arn!r}, got {signer!r}"
        )

    return ALBClaims(
        sub=claims.get("sub", ""),
        email=claims.get("email", ""),
        name=claims.get("name") or claims.get("preferred_username", ""),
        signer=signer,
    )


def _get_alb_public_key(kid: str, region: str) -> str:
    """ALB 公钥. kid 滚动期长, 简单进程内 dict 缓存."""
    if kid in _alb_key_cache:
        return _alb_key_cache[kid]

    url = f"https://public-keys.auth.elb.{region}.amazonaws.com/{kid}"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"failed to fetch ALB public key: {exc}")

    pem = resp.text
    _alb_key_cache[kid] = pem
    return pem


def _reset_alb_key_cache() -> None:
    """测试用: 清缓存."""
    _alb_key_cache.clear()
