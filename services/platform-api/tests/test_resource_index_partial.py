"""update_status_if_changed 部分更新 + create_stub (A3)。

部分更新只 SET metadata 的状态字段 (点路径), 不碰业务字段。
去重比对 phase/started_at/ended_at/priority_class (= A2, 不比 message/rv)。
三态: updated / skipped (去重命中) / absent (行不存在)。
"""
from app.repositories.resource_index import (
    _DEDUP_FIELDS,
    _STATUS_FIELDS,
    _build_status_update_expr,
)


def test_status_fields_and_dedup_fields():
    assert set(_STATUS_FIELDS) >= {
        "phase", "started_at", "ended_at", "last_condition_message",
        "priority_class", "status_detail", "kueue_status",
        "k8s_resource_version",
    }
    assert _DEDUP_FIELDS == (
        "phase", "started_at", "ended_at", "priority_class", "endpoint_url",
        "status_detail", "kueue_status",
    )


def test_build_status_update_expr_only_sets_status_fields():
    md = {"phase": "Running", "started_at": "t1", "ended_at": None,
          "last_condition_message": "m", "priority_class": "p"}
    update_expr, cond_expr, names, values = _build_status_update_expr(
        workspace_id="ws-1", resource_version=100, md=md,
    )
    # UpdateExpression 只 SET metadata.<状态字段>, 点路径
    assert update_expr.startswith("SET ")
    assert "#md.#phase = :phase" in update_expr
    assert "#md.#rv = :rv" in update_expr
    # 不 SET 业务字段
    assert "image" not in update_expr and "instance_type" not in update_expr
    # 去重条件: rv 更新 且 四字段任一变
    assert "#md.#rv < :rv" in cond_expr
    assert ":phase" in values and ":priority_class" in values
    # message 不进去重条件
    assert "last_condition_message" not in cond_expr
    assert names["#md"] == "metadata"
    # 状态字段值都在 values (含 message, 因为它要被 SET, 只是不进去重)
    assert values[":last_condition_message"] == "m"


def test_build_status_update_expr_none_values():
    # md 带 kueue_status 有值: 其余字段为 None 仍 SET, 全 _DEDUP_FIELDS 进去重
    md = {"phase": "Pending", "started_at": None, "ended_at": None,
          "last_condition_message": None, "priority_class": None,
          "kueue_status": "Queued"}
    update_expr, cond_expr, names, values = _build_status_update_expr(
        workspace_id="ws-1", resource_version=50, md=md,
    )
    assert values[":started_at"] is None
    assert values[":priority_class"] is None
    for f in _DEDUP_FIELDS:
        assert f"#md.#{f} <> :{f}" in cond_expr


def test_kueue_status_none_not_set_and_active_ws_untouched():
    # 关键正确性: kueue_status=None (查不到Workload且CR非终态) → 不SET kueue_status,
    # 不动 active_ws (既不SET也不REMOVE), 保持DDB旧值。其余字段照常SET。
    md = {"phase": "Created", "started_at": "t1", "ended_at": None,
          "last_condition_message": "m", "priority_class": "p",
          "kueue_status": None}
    update_expr, cond_expr, names, values = _build_status_update_expr(
        workspace_id="ws-1", resource_version=100, md=md,
    )
    # 其余状态字段照常 SET
    assert "#md.#phase = :phase" in update_expr
    # kueue_status 不 SET
    assert "#md.#kueue_status = :kueue_status" not in update_expr
    assert ":kueue_status" not in values
    # active_ws 既不 SET 也不 REMOVE
    assert "active_ws" not in update_expr
    # kueue_status 不进去重条件 (None 不应触发写)
    assert "#md.#kueue_status" not in cond_expr
    # 也不走补写旁路
    assert "attribute_not_exists(#md.#kueue_status)" not in cond_expr


def test_kueue_status_present_sets_and_active_ws_and_bypass():
    # kueue_status 有值 (活跃态) → SET + active_ws SET + 补写旁路在
    md = {"phase": "Running", "kueue_status": "PodsReady"}
    update_expr, cond_expr, names, values = _build_status_update_expr(
        workspace_id="ws-1", resource_version=100, md=md,
    )
    assert "#md.#kueue_status = :kueue_status" in update_expr
    assert values[":kueue_status"] == "PodsReady"
    # 活跃 → active_ws SET
    assert "active_ws = :active_ws" in update_expr
    assert values[":active_ws"] == "ws-1"
    # 补写旁路在
    assert "attribute_not_exists(#md.#kueue_status)" in cond_expr


def test_kueue_status_finished_removes_active_ws():
    # 终态 Finished → active_ws REMOVE (出稀疏 GSI)
    md = {"phase": "Stopped", "kueue_status": "Finished"}
    update_expr, _cond, _names, values = _build_status_update_expr(
        workspace_id="ws-1", resource_version=100, md=md,
    )
    assert "REMOVE" in update_expr and "active_ws" in update_expr.split("REMOVE")[1]
    assert ":active_ws" not in values
