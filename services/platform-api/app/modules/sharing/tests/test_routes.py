"""分享路由 handler 单测: 直接调 handler 函数 (绕过 AuthMiddleware, 与本仓
其它路由测试同法), 验证 body→orchestration→响应映射的接线正确。"""

import app.main  # noqa: F401


def _user():
    return {"user_id": "owner", "username": "owner", "is_admin": False}


async def _no_op_member(ws, user):
    return None


async def test_post_shares_calls_orchestration(monkeypatch):
    from app.modules.sharing.api import router as router_mod
    from app.modules.sharing import orchestration as orch
    from app.modules.sharing.api.schemas import ShareBody

    monkeypatch.setattr(router_mod, "assert_ws_member", _no_op_member)

    async def fake_share(ws, rt, rid, targets, user):
        return [
            {"res_type": rt, "res_id": rid, "target_username": t,
             "shared_by": "owner", "shared_at": "t"}
            for t in targets
        ]

    monkeypatch.setattr(orch, "share_resource", fake_share)

    body = ShareBody(res_type="dev", res_id="d1", target_usernames=["alice"])
    out = await router_mod.create_shares("ws1", body, _user())
    assert out[0].target_username == "alice"
    assert out[0].res_type == "dev"


async def test_get_shares(monkeypatch):
    from app.modules.sharing.api import router as router_mod
    from app.modules.sharing import orchestration as orch

    monkeypatch.setattr(router_mod, "assert_ws_member", _no_op_member)

    async def fake_list(ws, rt, rid, user):
        return [{"res_type": rt, "res_id": rid, "target_username": "alice",
                 "shared_by": "owner", "shared_at": "t"}]

    monkeypatch.setattr(orch, "list_shares", fake_list)

    out = await router_mod.list_resource_shares("ws1", "dev", "d1", _user())
    assert out[0].target_username == "alice"


async def test_delete_share(monkeypatch):
    from app.modules.sharing.api import router as router_mod
    from app.modules.sharing import orchestration as orch

    monkeypatch.setattr(router_mod, "assert_ws_member", _no_op_member)
    called = {}

    async def fake_unshare(ws, rt, rid, username, user):
        called["username"] = username

    monkeypatch.setattr(orch, "unshare_resource", fake_unshare)

    resp = await router_mod.delete_share("ws1", "dev", "d1", "alice", _user())
    assert resp.status_code == 204
    assert called["username"] == "alice"
