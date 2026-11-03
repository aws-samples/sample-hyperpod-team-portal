"""训练 delete 权限闸 + 审计写入测试 (mock, 不碰真 DDB/K8s)。

覆盖:
    - _assert_can_operate: creator 本人 / ws admin / 超管 放行; 无关用户 403; user=None 跳过
    - audit_training: 正确写 AuditLog (scope=ws, target_type=training_job)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.training.orchestration import lifecycle


_ROW = {
    "id": "job-1",
    "workspace_id": "ws-1",
    "creator_user_id": "alice",
    "display_name": "DDP 冒烟",
}


@pytest.mark.asyncio
class TestAssertCanOperate:
    async def test_creator_ok(self):
        # creator 本人放行 (不依赖 is_ws_admin)
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
class TestAuditTraining:
    async def test_append_called_with_correct_fields(self, monkeypatch):
        captured = {}

        async def fake_append(**kwargs):
            captured.update(kwargs)
            return {"event_id": "e1"}

        from app.repositories import audit_log as audit_repo
        monkeypatch.setattr(audit_repo, "append", fake_append)

        await lifecycle.audit_training(
            _ROW, {"user_id": "alice", "is_admin": False}, "training.create"
        )
        assert captured["operation"] == "training.create"
        assert captured["target_type"] == "training_job"
        assert captured["target_id"] == "job-1"
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

        await lifecycle.audit_training(
            _ROW, {"user_id": "admin", "is_admin": True}, "training.delete"
        )
        assert captured["actor_role"] == "platform-admin"
        assert captured["operation"] == "training.delete"

    async def test_audit_failure_swallowed(self, monkeypatch):
        async def boom(**kwargs):
            raise RuntimeError("ddb down")

        from app.repositories import audit_log as audit_repo
        monkeypatch.setattr(audit_repo, "append", boom)
        # 审计失败不抛 (不阻断主流程) → 不抛异常即通过
        await lifecycle.audit_training(_ROW, {"user_id": "alice"}, "training.create")
