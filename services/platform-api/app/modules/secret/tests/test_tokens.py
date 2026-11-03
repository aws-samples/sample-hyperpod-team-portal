"""通用 secret 编排单测 (B2 每人一把) · mock k8s, 不打真集群。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.secret.api.schemas import SecretKeyPut
from app.modules.secret.orchestration import tokens as svc


@pytest.fixture(autouse=True)
def _stub_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    """ws 成员 + namespace 反查 stub (成员校验/建 ns 不打 DDB)。"""
    monkeypatch.setattr(
        svc.ws_crud, "get_membership", AsyncMock(return_value={"role": "member"})
    )
    monkeypatch.setattr(
        svc.ws_crud,
        "get_workspace",
        AsyncMock(return_value={"namespace": "hyperpod-ns-team-a"}),
    )


def _user(uid: str = "alice") -> dict[str, Any]:
    return {"user_id": uid}


def test_secret_name_derived():
    assert svc.secret_name_for(_user("alice")) == "alice-secrets"


@pytest.mark.asyncio
async def test_put_key_writes_to_own_secret():
    k8s = SimpleNamespace(put_secret_key=AsyncMock(return_value=["GITHUB_TOKEN"]))
    view = await svc.put_key(
        k8s, "ws1", SecretKeyPut(key="GITHUB_TOKEN", value="ghp_x"), _user("alice")
    )
    assert view.keys == ["GITHUB_TOKEN"]
    call = k8s.put_secret_key.await_args
    assert call.args[0] == "hyperpod-ns-team-a"
    assert call.args[1] == "alice-secrets"
    assert call.args[2] == "GITHUB_TOKEN"
    assert call.args[3] == "ghp_x"


@pytest.mark.asyncio
async def test_get_view_returns_keys():
    k8s = SimpleNamespace(get_secret_keys=AsyncMock(return_value=["A", "B"]))
    view = await svc.get_view(k8s, "ws1", _user("alice"))
    assert view.keys == ["A", "B"]
    k8s.get_secret_keys.assert_awaited_once_with("hyperpod-ns-team-a", "alice-secrets")


@pytest.mark.asyncio
async def test_delete_key():
    k8s = SimpleNamespace(delete_secret_key=AsyncMock(return_value=[]))
    view = await svc.delete_key(k8s, "ws1", "GITHUB_TOKEN", _user("alice"))
    assert view.keys == []
    k8s.delete_secret_key.assert_awaited_once_with(
        "hyperpod-ns-team-a", "alice-secrets", "GITHUB_TOKEN"
    )


@pytest.mark.asyncio
async def test_non_member_forbidden(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(svc.ws_crud, "get_membership", AsyncMock(return_value=None))
    k8s = SimpleNamespace(get_secret_keys=AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as ei:
        await svc.get_view(k8s, "ws1", _user("outsider"))
    assert ei.value.status_code == 403
