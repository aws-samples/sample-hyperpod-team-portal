"""ApiTokens Repository 纯逻辑测试: 过期判断 + item 构造."""
from app.repositories.api_tokens import build_item, is_expired


def test_build_item_shape():
    item = build_item(
        username="foxqin",
        token_hash="deadbeef",
        token_display="hypd_aweb**************cdce",
        created_at="2026-06-12T00:00:00+00:00",
        expires_at="2026-09-10T00:00:00+00:00",
    )
    assert item["username"] == "foxqin"
    assert item["token_hash"] == "deadbeef"
    assert item["token_display"] == "hypd_aweb**************cdce"
    assert item["created_at"] == "2026-06-12T00:00:00+00:00"
    assert item["expires_at"] == "2026-09-10T00:00:00+00:00"


def test_build_item_never_expire():
    item = build_item(
        username="foxqin",
        token_hash="x",
        token_display="y",
        created_at="2026-06-12T00:00:00+00:00",
        expires_at=None,
    )
    assert item["expires_at"] is None


def test_is_expired_none_never_expires():
    assert is_expired(None, now_iso="2099-01-01T00:00:00+00:00") is False


def test_is_expired_past():
    assert is_expired(
        "2026-01-01T00:00:00+00:00", now_iso="2026-06-12T00:00:00+00:00"
    ) is True


def test_is_expired_future():
    assert is_expired(
        "2099-01-01T00:00:00+00:00", now_iso="2026-06-12T00:00:00+00:00"
    ) is False
