"""kueue_status 补写旁路: 现无 kueue_status 时即使 rv 未增长也能写 (修复存量行 None 卡住)。"""
from app.repositories import resource_index as ri


def test_cond_expr_has_kueue_backfill_bypass():
    _upd, cond, names, values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5, md={"kueue_status": "started"}
    )
    assert "#kueue_status" in cond
    assert ":kueue_status" in cond or "attribute_not_exists(#md.#kueue_status)" in cond
    assert names.get("#kueue_status") == "kueue_status"
    assert values.get(":kueue_status") == "started"


def test_kueue_bypass_not_gated_by_rv_guard():
    """补写旁路必须在 rv 守卫之外 (顶层 OR), 否则存量行 rv 稳定时 None 仍补不上。

    结构: cond = ( <主条件含 rv 守卫 + dedup> ) OR attribute_not_exists(#md.#kueue_status)
    顶层 OR 之后的尾巴必须是裸的 attribute_not_exists(#md.#kueue_status), 不带 rv 守卫。
    """
    _upd, cond, _n, _v = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5, md={"kueue_status": "started"}
    )
    # 旁路以顶层 ") OR attribute_not_exists(#md.#kueue_status)" 收尾 (在 dedup 组的右括号之后)。
    assert cond.rstrip().endswith(") OR attribute_not_exists(#md.#kueue_status)")


def test_cond_expr_main_rv_guard_still_present():
    _upd, cond, _n, _v = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5, md={"kueue_status": "started"}
    )
    assert "#md.#rv < :rv" in cond
