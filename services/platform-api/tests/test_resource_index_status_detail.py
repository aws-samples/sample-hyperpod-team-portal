"""验证 status_detail 进入 informer 状态字段集合 (写入 / 去重 / 部分更新)。"""
from app.repositories import resource_index as ri


def test_status_detail_in_status_fields():
    assert "status_detail" in ri._STATUS_FIELDS


def test_status_detail_in_dedup_fields():
    assert "status_detail" in ri._DEDUP_FIELDS


def test_status_update_expr_sets_status_detail():
    md = {
        "phase": "Running",
        "started_at": None,
        "ended_at": None,
        "last_condition_message": "m",
        "priority_class": None,
        "endpoint_url": None,
        "status_detail": {"conditions": []},
    }
    update_expr, cond_expr, names, values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5, md=md
    )
    # SET 子句覆盖 metadata.status_detail
    assert "#status_detail" in names
    assert names["#status_detail"] == "status_detail"
    assert ":status_detail" in values
    assert values[":status_detail"] == {"conditions": []}
    assert "#md.#status_detail = :status_detail" in update_expr
