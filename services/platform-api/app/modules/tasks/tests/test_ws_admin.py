"""共享鉴权 is_ws_admin / assert_ws_admin (超管 OR ws admin)。"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core import security


@pytest.mark.asyncio
async def test_superadmin_is_ws_admin():
    # 超管直接 True, 不查 membership
    assert await security.is_ws_admin("ws-1", {"is_admin": True}) is True


@pytest.mark.asyncio
async def test_ws_role_admin_is_ws_admin(monkeypatch):
    monkeypatch.setattr(
        security, "_get_membership",
        AsyncMock(return_value={"role": "admin"}),
    )
    user = {"is_admin": False, "username": "alice"}
    assert await security.is_ws_admin("ws-1", user) is True


@pytest.mark.asyncio
async def test_member_is_not_ws_admin(monkeypatch):
    monkeypatch.setattr(
        security, "_get_membership",
        AsyncMock(return_value={"role": "member"}),
    )
    user = {"is_admin": False, "username": "bob"}
    assert await security.is_ws_admin("ws-1", user) is False


@pytest.mark.asyncio
async def test_none_user_is_not_ws_admin():
    assert await security.is_ws_admin("ws-1", None) is False


@pytest.mark.asyncio
async def test_assert_ws_admin_raises_403_for_member(monkeypatch):
    monkeypatch.setattr(
        security, "_get_membership",
        AsyncMock(return_value={"role": "member"}),
    )
    with pytest.raises(HTTPException) as exc:
        await security.assert_ws_admin("ws-1", {"is_admin": False, "username": "bob"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_assert_ws_admin_passes_for_superadmin():
    # 不抛即通过
    await security.assert_ws_admin("ws-1", {"is_admin": True})
