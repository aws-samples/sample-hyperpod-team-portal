"""成员自我保护: ws 管理员不能删/降自己, 平台超管不受限。"""
import pytest
from fastapi import HTTPException

from app.modules.workspace.orchestration import lifecycle as lc


def _actor(username, is_admin=False):
    return {"username": username, "user_id": username, "is_admin": is_admin}


def test_remove_self_blocked_for_ws_admin():
    with pytest.raises(HTTPException) as ei:
        lc._assert_member_action_allowed(_actor("alice"), "alice", new_role=None)
    assert ei.value.status_code == 403


def test_remove_self_allowed_for_platform_admin():
    lc._assert_member_action_allowed(_actor("alice", is_admin=True), "alice", new_role=None)


def test_remove_other_allowed():
    lc._assert_member_action_allowed(_actor("alice"), "bob", new_role=None)


def test_downgrade_self_blocked():
    with pytest.raises(HTTPException) as ei:
        lc._assert_member_action_allowed(_actor("alice"), "alice", new_role="member")
    assert ei.value.status_code == 403


def test_change_self_to_admin_allowed():
    lc._assert_member_action_allowed(_actor("alice"), "alice", new_role="admin")


def test_downgrade_self_allowed_for_platform_admin():
    lc._assert_member_action_allowed(_actor("alice", is_admin=True), "alice", new_role="member")
