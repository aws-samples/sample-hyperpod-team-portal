"""API Token 纯函数测试: 生成 / hash / 脱敏展示串."""
import hashlib

from app.core.token_util import (
    TOKEN_PREFIX,
    generate_token,
    hash_token,
    mask_token,
)


def test_generate_token_has_prefix_and_entropy():
    tok = generate_token()
    assert tok.startswith(TOKEN_PREFIX)  # "hypd_"
    # 前缀后至少 40 字符 (32 字节 base62 ≈ 43 char)
    assert len(tok) - len(TOKEN_PREFIX) >= 40


def test_generate_token_is_random():
    assert generate_token() != generate_token()


def test_hash_token_is_sha256_hex():
    tok = "hypd_abc123"
    assert hash_token(tok) == hashlib.sha256(tok.encode()).hexdigest()


def test_hash_token_stable():
    assert hash_token("hypd_x") == hash_token("hypd_x")


def test_mask_token_front4_back4():
    # 前缀后取首4 + 尾4, 中间打码
    tok = "hypd_aweb1234567890cdce"
    masked = mask_token(tok)
    assert masked.startswith("hypd_aweb")
    assert masked.endswith("cdce")
    assert "*" in masked
    # 不泄露中间
    assert "1234567890" not in masked
