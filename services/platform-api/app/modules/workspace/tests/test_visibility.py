"""GET /workspaces 可见性决策 (越权漏洞修复, 2026-06-14)。

锁死: 可见范围只由已认证身份决定, 不信前端传的 user_id。
"""
from __future__ import annotations

from app.modules.workspace.domain.visibility import effective_visibility_user_id


def test_platform_admin_sees_all():
    # 超管 → None = crud 不按 user 过滤 = 全部 ws
    assert effective_visibility_user_id({"user_id": "root", "is_admin": True}) is None


def test_normal_user_limited_to_self():
    # 普通用户 → 限定到自己的 username
    uid = effective_visibility_user_id({"user_id": "alice", "is_admin": False})
    assert uid == "alice"


def test_falls_back_to_username_then_id():
    assert effective_visibility_user_id({"username": "bob"}) == "bob"
    assert effective_visibility_user_id({"id": "carol"}) == "carol"
