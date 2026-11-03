from worker.phase import derive_phase


def _cr(conditions=None, completion_time=None):
    return {
        "metadata": {"name": "j1", "resourceVersion": "1005"},
        "status": {
            "conditions": conditions or [],
            **({"completionTime": completion_time} if completion_time else {}),
        },
    }


def test_phase_empty_when_no_true_conditions():
    # 无 True condition → phase 空串 (待真集群验证是否真会出现)
    assert derive_phase(_cr()).phase == ""


def test_phase_single_true_type():
    pr = derive_phase(
        _cr([{"type": "Running", "status": "True",
              "lastTransitionTime": "2026-06-02T10:00:00Z"}])
    )
    assert pr.phase == "Running"
    assert pr.started_at == "2026-06-02T10:00:00Z"


def test_phase_single_state_latest_timestamp():
    # 多个 True → 取 lastTransitionTime 最新的单个 (不再 "/" 拼接)
    pr = derive_phase(
        _cr([
            {"type": "Created", "status": "True",
             "lastTransitionTime": "2026-06-21T04:56:05Z"},
            {"type": "Running", "status": "True",
             "lastTransitionTime": "2026-06-21T04:57:54Z"},
        ])
    )
    assert pr.phase == "Running"


def test_phase_same_timestamp_uses_priority():
    # 时间戳相同 → 固定优先级: 终态 Failed 优先于 Created
    pr = derive_phase(
        _cr([
            {"type": "Created", "status": "True",
             "lastTransitionTime": "2026-06-21T04:56:05Z"},
            {"type": "Failed", "status": "True",
             "lastTransitionTime": "2026-06-21T04:56:05Z"},
        ])
    )
    assert pr.phase == "Failed"


def test_phase_no_timestamp_uses_priority():
    # 都无 lastTransitionTime (实证可能) → 全部相同空串时间戳 → 按优先级
    pr = derive_phase(
        _cr([
            {"type": "Created", "status": "True"},
            {"type": "Running", "status": "True"},
            {"type": "Initialized", "status": "False"},
        ])
    )
    # Running 优先级高于 Created → 单个 Running
    assert pr.phase == "Running"


def test_started_at_prefers_running_then_created():
    pr = derive_phase(
        _cr([
            {"type": "Created", "status": "True",
             "lastTransitionTime": "2026-06-02T09:00:00Z"},
            {"type": "Running", "status": "True",
             "lastTransitionTime": "2026-06-02T10:00:00Z"},
        ])
    )
    # Running 优先于 Created
    assert pr.started_at == "2026-06-02T10:00:00Z"


def test_started_at_falls_back_to_created():
    pr = derive_phase(
        _cr([{"type": "Created", "status": "True",
              "lastTransitionTime": "2026-06-02T09:00:00Z"}])
    )
    assert pr.started_at == "2026-06-02T09:00:00Z"


def test_ended_at_from_terminal_condition():
    # ended_at 取终态 condition 的 lastTransitionTime (CR 无 completionTime)
    pr = derive_phase(
        _cr([{"type": "Completed", "status": "True",
              "lastTransitionTime": "2026-06-02T12:00:00Z"}])
    )
    assert "Completed" in pr.phase
    assert pr.ended_at == "2026-06-02T12:00:00Z"


def test_ended_at_none_when_running():
    # 无终态 condition (运行中) → ended_at None (前端继续用当前时间)
    pr = derive_phase(
        _cr([{"type": "Created", "status": "True",
              "lastTransitionTime": "2026-06-02T09:00:00Z"}])
    )
    assert pr.ended_at is None


def test_last_condition_message_is_last_entry():
    pr = derive_phase(
        _cr([
            {"type": "Created", "status": "True", "message": "created"},
            {"type": "Running", "status": "True", "message": "running now"},
        ])
    )
    assert pr.last_condition_message == "running now"
