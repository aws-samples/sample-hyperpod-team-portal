"""seed_images 测试: 建 ws 自动注册基础镜像 (去重 + 跳空 + uses)。"""


async def test_seed_images_dedup_and_skip_empty(monkeypatch):
    from app.modules.registry.orchestration import images

    # 已注册一个 uri-a; put 记录新写入的
    async def fake_list_all(ws):
        return [{"image_uri": "uri-a", "sort_key": "img#x"}]

    written = []

    async def fake_put(*, workspace_id, sort_key, item_fields):
        written.append(item_fields)
        return {"created_at": "t", **item_fields}

    monkeypatch.setattr(images.repo, "list_all", fake_list_all)
    monkeypatch.setattr(images.repo, "put", fake_put)

    n = await images.seed_images(
        "ws-1",
        [
            ("uri-a", "A"),     # 已存在 → 跳过
            ("", "empty"),      # 空 → 跳过
            ("uri-b", "B"),     # 新 → 写
            ("uri-b", "B-dup"), # 本批重复 → 跳过
            ("uri-c", ""),      # 新, 无名 → 用 URI 末段
        ],
        "creator1",
    )

    assert n == 2
    uris = [w["image_uri"] for w in written]
    assert uris == ["uri-b", "uri-c"]
    assert all(w["uses"] == ["dev"] for w in written)
    assert all(w["source"] == "ecr-private" for w in written)
    assert all(w["creator_username"] == "creator1" for w in written)
    # 无名的 uri-c → display_name 用 URI 末段兜底
    assert written[1]["display_name"] == "uri-c"


async def test_seed_images_custom_uses(monkeypatch):
    from app.modules.registry.orchestration import images

    async def fake_list_all(ws):
        return []

    written = []

    async def fake_put(*, workspace_id, sort_key, item_fields):
        written.append(item_fields)
        return {"created_at": "t", **item_fields}

    monkeypatch.setattr(images.repo, "list_all", fake_list_all)
    monkeypatch.setattr(images.repo, "put", fake_put)

    n = await images.seed_images(
        "ws-1", [("uri-x", "X")], "c", uses=["dev", "training"]
    )
    assert n == 1
    assert written[0]["uses"] == ["dev", "training"]
