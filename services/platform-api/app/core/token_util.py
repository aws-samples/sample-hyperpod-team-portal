"""API Token 纯函数: 生成 / hash / 脱敏展示串 (无 IO, 易测).

token 格式: hypd_<random>
    - 前缀 hypd_ 让中间件区分 API Token vs Cognito JWT
    - random = 32 字节, base62 编码 (urlsafe 去掉 +/= 后保留字母数字)
    - 不内嵌 username (避免泄露用户名); 验证靠 token_hash-index GSI
"""
from __future__ import annotations

import hashlib
import secrets
import string

TOKEN_PREFIX = "hypd_"
_ALPHABET = string.ascii_letters + string.digits  # base62
_RANDOM_LEN = 43  # ≈ 32 字节熵


def generate_token() -> str:
    """生成新明文 token (仅生成时存在, 不落库)."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(_RANDOM_LEN))
    return f"{TOKEN_PREFIX}{body}"


def hash_token(token: str) -> str:
    """sha256 hex. 落库只存 hash, 验证时把收到的 token 同样 hash 比对."""
    return hashlib.sha256(token.encode()).hexdigest()


def mask_token(token: str) -> str:
    """脱敏展示串: 前缀 + 首4 + 中间打码 + 尾4.

    例: hypd_aweb1234567890cdce -> hypd_aweb**************cdce
    """
    body = token[len(TOKEN_PREFIX):]
    if len(body) <= 8:
        # 异常短 token, 全打码 (防越界泄露)
        return f"{TOKEN_PREFIX}{'*' * len(body)}"
    front, back = body[:4], body[-4:]
    stars = "*" * (len(body) - 8)
    return f"{TOKEN_PREFIX}{front}{stars}{back}"
