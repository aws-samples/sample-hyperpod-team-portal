"""FSx 挂载 gid 约束: 非超管首挂被拦 / 只能挂 primary_gid 目录。"""
import pytest
from fastapi import HTTPException

from app.modules.workspace.orchestration import fsx as fsx_mod


def _actor(is_admin=False):
    return {"username": "alice", "is_admin": is_admin}


def test_first_mount_blocked_for_ws_admin():
    with pytest.raises(HTTPException) as ei:
        fsx_mod._assert_fsx_attach_allowed(_actor(), primary_gid=None, probed_gid=1001)
    assert ei.value.status_code == 403


def test_gid_mismatch_blocked_for_ws_admin():
    with pytest.raises(HTTPException) as ei:
        fsx_mod._assert_fsx_attach_allowed(_actor(), primary_gid=1001, probed_gid=2002)
    assert ei.value.status_code == 403


def test_gid_match_allowed_for_ws_admin():
    fsx_mod._assert_fsx_attach_allowed(_actor(), primary_gid=1001, probed_gid=1001)


def test_platform_admin_first_mount_allowed():
    fsx_mod._assert_fsx_attach_allowed(_actor(is_admin=True), primary_gid=None, probed_gid=1001)


def test_platform_admin_any_gid_allowed():
    fsx_mod._assert_fsx_attach_allowed(_actor(is_admin=True), primary_gid=1001, probed_gid=2002)
