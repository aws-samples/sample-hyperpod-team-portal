"""kueue_status 读出 (_ri_to_dev) + 在业务字段白名单 (sync 能落库)。"""
from app.modules.devinstance.persistence import crud


def test_ri_to_dev_reads_kueue_status():
    item = {
        "resource_id": "d1",
        "workspace_id": "ws-1",
        "metadata": {"phase": "Available", "kueue_status": "started"},
    }
    out = crud._ri_to_dev(item)
    assert out["kueue_status"] == "started"


def test_ri_to_dev_kueue_status_absent_is_none():
    item = {"resource_id": "d2", "workspace_id": "ws-1", "metadata": {"phase": "Available"}}
    out = crud._ri_to_dev(item)
    assert out["kueue_status"] is None


def test_kueue_status_not_in_business_whitelist():
    # KS-4: kueue_status 已归 informer 状态字段 (repo._STATUS_FIELDS), 由 informer 的
    # update_status_if_changed 写。故不再属于 platform-api 业务字段白名单 — 若误入白名单,
    # repo._build_business_update_expr 会因它是状态字段而抛 ValueError。
    assert "kueue_status" not in crud._DEV_BUSINESS_FIELDS
