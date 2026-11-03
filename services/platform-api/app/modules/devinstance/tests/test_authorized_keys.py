"""add_authorized_key_flow 单测 · mock pod 查询/exec/权限。

断言:
    - pod Running + exec OK → {ok:True}, exec 命令用 argv 传公钥 (不拼脚本)
    - pod 未 Running / 无 pod → 400, 不 exec
    - exec 返 None / 无成功标记 → 500
    - 非创建者/超管/被分享者 → 403
    - 公钥格式非法 → schema 校验拒绝
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.devinstance.api.schemas import AuthorizedKeyAdd
from app.modules.devinstance.orchestration import authorized_keys as authk

_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyDataHere user@laptop"


def _row(creator: str = "alice") -> dict[str, Any]:
    return {
        "id": "dev-1",
        "workspace_id": "ws-1",
        "creator_user_id": creator,
        "k8s_namespace": "hyperpod-ns-team-a-nlp",
        "k8s_workspace_name": "my-dev-abc123",
    }


def _running_pod() -> dict[str, Any]:
    return {"metadata": {"name": "my-dev-abc123-pod-xyz"}, "status": {"phase": "Running"}}


@pytest.fixture
def _k8s():
    k8s = MagicMock()
    k8s.get_pod_by_workspace = AsyncMock(return_value=_running_pod())
    k8s.exec_in_pod = AsyncMock(return_value="__AUTHKEY_OK__\n")
    return k8s


@pytest.mark.asyncio
async def test_success_argv_passing(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row()))
    out = await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "alice"})
    assert out["ok"] is True
    # 公钥作为 argv 末位传入 (不出现在脚本字符串里)
    cmd = _k8s.exec_in_pod.await_args.kwargs["command"]
    assert cmd[0] == "sh" and cmd[1] == "-c"
    assert cmd[-1] == _KEY
    assert _KEY not in cmd[2]  # 脚本文本不含公钥
    assert 'grep -qxF "$1"' in cmd[2]


@pytest.mark.asyncio
async def test_pod_not_running_400(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row()))
    _k8s.get_pod_by_workspace = AsyncMock(
        return_value={"metadata": {"name": "p"}, "status": {"phase": "Pending"}}
    )
    with pytest.raises(HTTPException) as exc:
        await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "alice"})
    assert exc.value.status_code == 400
    _k8s.exec_in_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_pod_400(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row()))
    _k8s.get_pod_by_workspace = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "alice"})
    assert exc.value.status_code == 400
    _k8s.exec_in_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_exec_fail_500(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row()))
    _k8s.exec_in_pod = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "alice"})
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_exec_no_ok_mark_500(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row()))
    _k8s.exec_in_pod = AsyncMock(return_value="permission denied")
    with pytest.raises(HTTPException) as exc:
        await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "alice"})
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_non_creator_non_shared_403(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row("alice")))
    monkeypatch.setattr(
        "app.modules.sharing.visibility.shared_res_ids",
        AsyncMock(return_value=set()),
    )
    with pytest.raises(HTTPException) as exc:
        await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "bob"})
    assert exc.value.status_code == 403
    _k8s.exec_in_pod.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_user_allowed(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row("alice")))
    monkeypatch.setattr(
        "app.modules.sharing.visibility.shared_res_ids",
        AsyncMock(return_value={"dev-1"}),
    )
    out = await authk.add_authorized_key_flow(_k8s, "dev-1", _KEY, {"user_id": "bob"})
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_superadmin_allowed(monkeypatch, _k8s):
    monkeypatch.setattr(authk, "_get_or_404", AsyncMock(return_value=_row("alice")))
    out = await authk.add_authorized_key_flow(
        _k8s, "dev-1", _KEY, {"user_id": "root", "is_admin": True}
    )
    assert out["ok"] is True


@pytest.mark.parametrize(
    "bad",
    [
        "not-a-key",
        "ssh-ed25519",  # 缺 base64
        "ecdsa-sha2-nistp999 AAAA",  # 未知曲线
        'ssh-rsa AAAA\nrm -rf /',  # 换行注入企图
        "-----BEGIN OPENSSH PRIVATE KEY-----",  # 私钥
    ],
)
def test_invalid_pubkey_rejected(bad):
    with pytest.raises(ValueError):
        AuthorizedKeyAdd(public_key=bad)


def test_valid_pubkey_accepted():
    assert AuthorizedKeyAdd(public_key=f"  {_KEY}  ").public_key == _KEY
    assert AuthorizedKeyAdd(public_key="ssh-rsa AAAAB3NzaC1yc2E=").public_key
