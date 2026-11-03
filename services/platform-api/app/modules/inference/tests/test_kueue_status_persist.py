"""推理 kueue_status 读写对称 (整行 put 不丢 informer 值) + mark_stopped 置 finished。"""
import pytest
from unittest.mock import AsyncMock  # noqa: F401

from app.modules.inference.persistence import crud


def test_ri_to_inf_reads_kueue_status():
    item = {"resource_id": "i1", "workspace_id": "ws-1",
            "metadata": {"phase": "DeploymentComplete", "kueue_status": "started"}}
    out = crud._ri_to_inf(item)
    assert out["kueue_status"] == "started"


def test_inf_to_md_writes_kueue_status():
    md = crud._inf_to_md({"name": "ep", "kueue_status": "started"})
    assert md["kueue_status"] == "started"


def test_roundtrip_preserves_kueue_status():
    item = {"resource_id": "i2", "workspace_id": "ws-1",
            "metadata": {"kueue_status": "queued"}}
    row = crud._ri_to_inf(item)
    md = crud._inf_to_md(row)
    assert md["kueue_status"] == "queued"


@pytest.mark.asyncio
async def test_mark_stopped_sets_finished(monkeypatch):
    # mark_stopped 改走部分更新 mark_stopped_inference (取代整行 upsert),
    # 不再调 upsert_resource。断言它被调到 + 返回 row 反映停止终态。
    captured = {}

    async def fake_mark_stopped(ws_id, rid, *a, **kw):
        captured["ws_id"] = ws_id
        captured["rid"] = rid
        captured["ended_at"] = kw.get("ended_at")
        return {}

    async def fake_clear_deleted(*a, **k):
        return {}

    monkeypatch.setattr(crud.ri_repo, "mark_stopped_inference", fake_mark_stopped)
    monkeypatch.setattr(crud.ri_repo, "clear_deleted", fake_clear_deleted)
    row = {"id": "i9", "workspace_id": "ws-1", "creator_user_id": "u",
           "k8s_endpoint_name": "ep", "display_name": "ep", "phase": "DeploymentComplete",
           "kueue_status": "started"}
    out = await crud.mark_stopped(None, row)
    assert captured["ws_id"] == "ws-1"
    assert captured["rid"] == "i9"
    assert out["kueue_status"] == "Finished"
    # 停止即结束: ended_at 必须落到 DDB 和返回的 row 上, 否则前端运行时长按当前时间一直涨
    assert captured["ended_at"], "mark_stopped 没把 ended_at 传给 repo"
    assert out["ended_at"] == captured["ended_at"]
    assert out["phase"] == "Stopped"
    assert out["endpoint_url"] is None
    assert out["stop_requested"] is True
