"""状态回收 + 成功自动注册测试。"""


async def test_reconcile_success_registers(monkeypatch):
    from app.modules.registry.orchestration import builds

    row = {
        "sort_key": "build#b1",
        "status": "building",
        "codebuild_id": "p:1",
        "target_repo": "hypd-demo-ws-ws1",
        "target_tag": "img:1.0",
        "target_uri": "111.dkr.ecr/hypd-demo-ws-ws1:1.0",
        "uses": ["training"],
        "created_at": "t",
    }

    async def fake_bgb(ids):
        return [
            {"id": "p:1", "buildStatus": "SUCCEEDED", "logs": {"deepLink": "http://logs"}}
        ]

    reg_called = {}

    async def fake_register(ws, body, user):
        reg_called["uri"] = body.image_uri
        reg_called["source"] = body.source
        return {"id": "img-new"}

    puts = []

    async def fake_put(*, workspace_id, sort_key, item_fields):
        puts.append(item_fields)
        return {}

    monkeypatch.setattr(builds.codebuild, "batch_get_builds", fake_bgb)
    monkeypatch.setattr(builds.images_svc, "register_image", fake_register)
    monkeypatch.setattr(builds.repo, "put", fake_put)

    await builds._reconcile_building("ws1", [row], {"user_id": "u"})

    assert reg_called["source"] == "built"
    assert reg_called["uri"].endswith(":1.0")
    assert puts[0]["status"] == "success"
    assert puts[0]["registered_image_id"] == "img-new"


async def test_reconcile_failed(monkeypatch):
    from app.modules.registry.orchestration import builds

    row = {
        "sort_key": "build#b2",
        "status": "building",
        "codebuild_id": "p:2",
        "target_tag": "img:1.0",
        "uses": ["training"],
        "created_at": "t",
    }

    async def fake_bgb(ids):
        return [{"id": "p:2", "buildStatus": "FAILED", "logs": {"deepLink": "http://l"}}]

    puts = []

    async def fake_put(*, workspace_id, sort_key, item_fields):
        puts.append(item_fields)
        return {}

    monkeypatch.setattr(builds.codebuild, "batch_get_builds", fake_bgb)
    monkeypatch.setattr(builds.repo, "put", fake_put)

    await builds._reconcile_building("ws1", [row], {"user_id": "u"})
    assert puts[0]["status"] == "failed"
    assert puts[0]["logs_url"] == "http://l"
