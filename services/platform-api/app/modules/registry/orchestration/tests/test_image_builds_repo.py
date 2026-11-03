"""ImageBuilds 表 key helper + repository.put 组装测试 (asyncio_mode=auto)。"""

from app.adapters.ddb import tables


def test_image_build_key():
    assert tables.image_build_key("abc") == "build#abc"
    assert tables.image_build_prefix() == "build#"


async def test_put_assembles_item(monkeypatch):
    captured = {}

    async def fake_put_item(table, item, *, ensure_new=False):
        captured["item"] = item

    async def fake_get_item(table, key):
        return None

    from app.adapters.ddb import base

    monkeypatch.setattr(base, "put_item", fake_put_item)
    monkeypatch.setattr(base, "get_item", fake_get_item)

    from app.repositories import image_builds as repo

    row = await repo.put(
        workspace_id="ws1",
        sort_key=tables.image_build_key("b1"),
        item_fields={"status": "building", "target_tag": "x:1"},
    )
    assert captured["item"]["workspace_id"] == "ws1"
    assert captured["item"]["sort_key"] == "build#b1"
    assert captured["item"]["status"] == "building"
    assert "created_at" in captured["item"] and "updated_at" in captured["item"]
    assert row["status"] == "building"
