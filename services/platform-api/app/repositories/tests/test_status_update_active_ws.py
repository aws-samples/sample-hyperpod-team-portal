"""_build_status_update_expr 联动 active_ws: 活跃 SET, finished REMOVE。"""
from app.repositories import resource_index as ri


def test_set_active_ws_when_started():
    expr, _cond, names, values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5,
        md={"phase": "Running", "kueue_status": "started"},
    )
    assert "active_ws = :active_ws" in expr
    assert "REMOVE" not in expr
    assert values[":active_ws"] == "ws-1"


def test_remove_active_ws_when_finished():
    expr, _cond, names, values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5,
        md={"phase": "Stopped", "kueue_status": "finished"},
    )
    assert "REMOVE active_ws" in expr
    assert ":active_ws" not in values


def test_finished_but_occupying_keeps_active_ws():
    # 训练 Failed (kueue_status=Finished) 但 Pod 还占卡 → active_ws 保留 (留在活跃列表),
    # 让占卡的失败任务可见, 不从"全部活跃"消失。occupying_resources 标记只用于算
    # active_ws, 不落库 (做法1)。
    expr, _cond, names, values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5,
        md={
            "phase": "Failed",
            "kueue_status": "Finished",
            "occupying_resources": True,
        },
    )
    # active_ws 仍 SET (占卡 → 活跃)
    assert "active_ws = :active_ws" in expr
    assert values[":active_ws"] == "ws-1"
    assert "REMOVE active_ws" not in expr
    # occupying_resources 不落库 (不进 metadata SET)
    assert "occupying_resources" not in expr
    assert ":occupying_resources" not in values
    # kueue_status 仍写 Finished (忠于 Workload)
    assert values[":kueue_status"] == "Finished"


def test_finished_not_occupying_removes_active_ws():
    # Failed 且 Pod 已释放 (occupying_resources=False/缺) → 正常 REMOVE active_ws
    expr, _cond, _names, values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5,
        md={
            "phase": "Failed",
            "kueue_status": "Finished",
            "occupying_resources": False,
        },
    )
    assert "REMOVE active_ws" in expr
    assert ":active_ws" not in values


def test_dedup_bypass_when_removing_active_ws():
    # active_ws 失配旁路: 这次目标 REMOVE active_ws (不活跃), 即使其它 dedup 字段没变,
    # 只要 DDB 还有 active_ws 就要放行写入 (否则去重 skip → active_ws 残留, 占卡 Pod 清后
    # 失败任务永远留在活跃列表)。
    _expr, cond, _names, _values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5,
        md={"phase": "Failed", "kueue_status": "Finished",
            "occupying_resources": False},
    )
    # 目标 REMOVE → 旁路: DDB 有 active_ws 就放行
    assert "attribute_exists(active_ws)" in cond


def test_dedup_bypass_when_setting_active_ws():
    # 目标 SET active_ws (活跃), 旁路: DDB 没有 active_ws 或值不等就放行
    # (占卡 Pod 出现 / 重启恢复活跃时, 即使其它字段没变也要写进 GSI)。
    _expr, cond, _names, _values = ri._build_status_update_expr(
        workspace_id="ws-1", resource_version=5,
        md={"phase": "Failed", "kueue_status": "Finished",
            "occupying_resources": True},
    )
    # 目标 SET → 旁路: DDB 缺 active_ws 或值不等就放行
    assert "attribute_not_exists(active_ws)" in cond
    assert "active_ws <> :active_ws" in cond
