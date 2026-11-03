"""Workspace 成员级鉴权 (is_ws_member / assert_ws_member).

越权漏洞修复 (2026-06-14): 普通成员能列出/查看所有 workspace 及其下资源。
根因 = 鉴权只有"平台超管"和"资源创建者"两层, 缺"ws 成员"这层闸门。
这些测试锁死成员判定逻辑, 不碰真 DDB (monkeypatch get_membership)。
"""
from __future__ import annotations

import pytest

from app.core import security


@pytest.fixture
def patch_membership(monkeypatch):
    """替换 _get_membership: 给定 {(ws_id, username): role} 表。"""

    def _install(table: dict[tuple[str, str], str]):
        async def fake(ws_id, username):
            role = table.get((ws_id, username))
            return {"role": role} if role is not None else None

        monkeypatch.setattr(security, "_get_membership", fake)

    return _install


async def test_member_with_role_member_is_ws_member(patch_membership):
    patch_membership({("ws-1", "alice"): "member"})
    user = {"user_id": "alice", "is_admin": False}
    assert await security.is_ws_member("ws-1", user) is True


async def test_owner_role_admin_is_ws_member(patch_membership):
    patch_membership({("ws-1", "bob"): "admin"})
    user = {"user_id": "bob", "is_admin": False}
    assert await security.is_ws_member("ws-1", user) is True


async def test_platform_admin_is_ws_member_without_membership(patch_membership):
    patch_membership({})  # 无任何 membership 记录
    user = {"user_id": "root", "is_admin": True}
    assert await security.is_ws_member("ws-1", user) is True


async def test_non_member_is_not_ws_member(patch_membership):
    patch_membership({("ws-1", "alice"): "member"})
    outsider = {"user_id": "mallory", "is_admin": False}
    assert await security.is_ws_member("ws-1", outsider) is False


async def test_none_user_is_not_ws_member(patch_membership):
    patch_membership({})
    assert await security.is_ws_member("ws-1", None) is False


async def test_assert_ws_member_raises_403_for_outsider(patch_membership):
    patch_membership({("ws-1", "alice"): "member"})
    outsider = {"user_id": "mallory", "is_admin": False}
    with pytest.raises(security.HTTPException) as exc:
        await security.assert_ws_member("ws-1", outsider)
    assert exc.value.status_code == 403


async def test_assert_ws_member_passes_for_member(patch_membership):
    patch_membership({("ws-1", "alice"): "member"})
    user = {"user_id": "alice", "is_admin": False}
    # 不抛即通过
    await security.assert_ws_member("ws-1", user)


# ===== _extract_bearer (logs stream/download query-token 身份解析用) =====


def test_extract_bearer_from_header():
    assert security._extract_bearer("Bearer abc123") == "abc123"


def test_extract_bearer_case_insensitive_and_trimmed():
    assert security._extract_bearer("bearer   tok  ") == "tok"


def test_extract_bearer_empty_returns_none():
    assert security._extract_bearer("") is None
    assert security._extract_bearer("Bearer ") is None
    assert security._extract_bearer("Basic xxx") is None


# ===== resolve_user_token (header 优先, 回退 query ?access_token=) =====


def test_resolve_token_prefers_header():
    # header 有 bearer 时, 忽略 query
    assert security.resolve_user_token("Bearer htok", "qtok") == "htok"


def test_resolve_token_falls_back_to_query():
    assert security.resolve_user_token("", "qtok") == "qtok"
    assert security.resolve_user_token("Basic xxx", "qtok") == "qtok"


def test_resolve_token_none_when_both_empty():
    assert security.resolve_user_token("", "") is None
    assert security.resolve_user_token("", None) is None
