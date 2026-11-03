"""推理 delete 权限闸 + 审计写入测试 (mock, 不碰真 DDB/K8s)。

覆盖:
    - _assert_can_operate: creator 本人 / ws admin / 超管 放行; 无关用户 403; user=None 跳过
    - audit_inference: 正确写 AuditLog (scope=ws, target_type=inference)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.inference.orchestration import lifecycle


_ROW = {
    "id": "inf-1",
    "workspace_id": "ws-1",
    "creator_user_id": "alice",
    "display_name": "qwen 推理",
}


@pytest.mark.asyncio
class TestAssertCanOperate:
    async def test_creator_ok(self):
        await lifecycle._assert_can_operate(_ROW, {"user_id": "alice", "is_admin": False})

    async def test_ws_admin_ok(self, monkeypatch):
        async def fake_is_ws_admin(ws, user):
            return True
        monkeypatch.setattr("app.core.security.is_ws_admin", fake_is_ws_admin)
        await lifecycle._assert_can_operate(_ROW, {"user_id": "bob", "is_admin": False})

    async def test_superadmin_ok(self, monkeypatch):
        async def fake_is_ws_admin(ws, user):
            return bool(user.get("is_admin"))
        monkeypatch.setattr("app.core.security.is_ws_admin", fake_is_ws_admin)
        await lifecycle._assert_can_operate(_ROW, {"user_id": "admin", "is_admin": True})

    async def test_stranger_403(self, monkeypatch):
        async def fake_is_ws_admin(ws, user):
            return False
        monkeypatch.setattr("app.core.security.is_ws_admin", fake_is_ws_admin)
        with pytest.raises(HTTPException) as exc:
            await lifecycle._assert_can_operate(_ROW, {"user_id": "stranger", "is_admin": False})
        assert exc.value.status_code == 403

    async def test_user_none_skips(self):
        await lifecycle._assert_can_operate(_ROW, None)


@pytest.mark.asyncio
class TestAuditInference:
    async def test_append_called_with_correct_fields(self, monkeypatch):
        captured = {}

        async def fake_append(**kwargs):
            captured.update(kwargs)
            return {"event_id": "e1"}

        from app.repositories import audit_log as audit_repo
        monkeypatch.setattr(audit_repo, "append", fake_append)

        await lifecycle.audit_inference(
            _ROW, {"user_id": "alice", "is_admin": False}, "inference.create"
        )
        assert captured["operation"] == "inference.create"
        assert captured["target_type"] == "inference"
        assert captured["target_id"] == "inf-1"
        assert captured["actor_user_id"] == "alice"
        assert captured["actor_role"] == "member"
        assert "ws-1" in captured["scope_key"]

    async def test_admin_role(self, monkeypatch):
        captured = {}

        async def fake_append(**kwargs):
            captured.update(kwargs)
            return {}

        from app.repositories import audit_log as audit_repo
        monkeypatch.setattr(audit_repo, "append", fake_append)

        await lifecycle.audit_inference(
            _ROW, {"user_id": "admin", "is_admin": True}, "inference.delete"
        )
        assert captured["actor_role"] == "platform-admin"
        assert captured["operation"] == "inference.delete"

    async def test_audit_failure_swallowed(self, monkeypatch):
        async def boom(**kwargs):
            raise RuntimeError("ddb down")

        from app.repositories import audit_log as audit_repo
        monkeypatch.setattr(audit_repo, "append", boom)
        await lifecycle.audit_inference(_ROW, {"user_id": "alice"}, "inference.create")
