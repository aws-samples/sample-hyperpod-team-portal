"""active_only 用 kueue_status<>finished 过滤; kueue_status 进状态字段集。"""
from app.repositories import resource_index as ri


def test_status_fields_has_kueue_status():
    assert "kueue_status" in ri._STATUS_FIELDS


def test_dedup_fields_has_kueue_status():
    assert "kueue_status" in ri._DEDUP_FIELDS
