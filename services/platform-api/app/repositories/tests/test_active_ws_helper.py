"""active_ws 取值: 活跃 (queued/started) 返 workspace_id, 否则 None。"""
from app.repositories import resource_index as ri


def test_active_for_started():
    assert ri._active_ws_value("ws-1", "started") == "ws-1"


def test_active_for_queued():
    assert ri._active_ws_value("ws-1", "queued") == "ws-1"


def test_none_for_finished():
    assert ri._active_ws_value("ws-1", "finished") is None


def test_none_for_missing():
    assert ri._active_ws_value("ws-1", None) is None
    assert ri._active_ws_value("ws-1", "") is None
