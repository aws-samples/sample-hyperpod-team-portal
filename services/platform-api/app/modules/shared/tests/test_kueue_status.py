from app.modules.shared.kueue_status import (
    KUEUE_FINISHED, KUEUE_QUEUED, KUEUE_ADMITTED, KUEUE_EVICTED,
    TERMINAL_STATES, ACTIVE_STATES, is_active, is_terminal,
    derive_kueue_status_from_workload,
)


def test_terminal_only_finished():
    assert TERMINAL_STATES == {"Finished"}


def test_evicted_is_active_not_terminal():
    assert KUEUE_EVICTED in ACTIVE_STATES
    assert is_active("Evicted") is True
    assert is_terminal("Evicted") is False


def test_is_active_six_states():
    for s in ("Queued", "QuotaReserved", "Admitted", "PodsReady", "Evicted"):
        assert is_active(s) is True
    assert is_active("Finished") is False


def test_is_active_legacy_lowercase():
    # 存量旧三态兼容
    assert is_active("queued") is True
    assert is_active("started") is True
    assert is_active("finished") is False


def test_is_terminal_legacy_and_new():
    assert is_terminal("Finished") is True
    assert is_terminal("finished") is True
    assert is_terminal("queued") is False


def test_none_and_empty_not_active_not_terminal():
    assert is_active(None) is False
    assert is_active("") is False
    assert is_terminal(None) is False


# ── derive_kueue_status_from_workload (Task 2: 用 spec §2 真样本) ──

def _wl(conds):
    return {"status": {"conditions": conds}}


def test_derive_running_picks_podsready():
    # 成功训练: QR+Admitted+PodsReady 都 True, 但未 Finished → PodsReady
    wl = _wl([
        {"type": "QuotaReserved", "status": "True"},
        {"type": "Admitted", "status": "True"},
        {"type": "PodsReady", "status": "True"},
    ])
    assert derive_kueue_status_from_workload(wl) == "PodsReady"


def test_derive_finished_wins_over_all():
    wl = _wl([
        {"type": "QuotaReserved", "status": "True"},
        {"type": "Admitted", "status": "True"},
        {"type": "Finished", "status": "True", "reason": "Succeeded"},
    ])
    assert derive_kueue_status_from_workload(wl) == "Finished"


def test_derive_crashloop_admitted():
    # crashloop: QR+Admitted True, PodsReady False → Admitted
    wl = _wl([
        {"type": "QuotaReserved", "status": "True"},
        {"type": "Admitted", "status": "True"},
        {"type": "PodsReady", "status": "False", "reason": "WaitForStart"},
    ])
    assert derive_kueue_status_from_workload(wl) == "Admitted"


def test_derive_queued_all_false_or_missing():
    # 排队中: QR False, PodsReady False, 无 Admitted → Queued
    wl = _wl([
        {"type": "PodsReady", "status": "False"},
        {"type": "QuotaReserved", "status": "False", "reason": "Pending"},
    ])
    assert derive_kueue_status_from_workload(wl) == "Queued"


def test_derive_empty_conditions_queued():
    assert derive_kueue_status_from_workload(_wl([])) == "Queued"


def test_derive_none_returns_none():
    assert derive_kueue_status_from_workload(None) is None


# ── worst_kueue_status: 组件间取最差 (取进展最小) ──

def test_worst_kueue_status_both_same():
    """两个相同状态 → 取该状态。"""
    from app.modules.shared.kueue_status import (
        KUEUE_PODS_READY, KUEUE_FINISHED,
        worst_kueue_status,
    )
    assert worst_kueue_status(KUEUE_PODS_READY, KUEUE_PODS_READY) == KUEUE_PODS_READY
    assert worst_kueue_status(KUEUE_FINISHED, KUEUE_FINISHED) == KUEUE_FINISHED


def test_worst_kueue_status_parametrized():
    """多组 (a, b, want) 测试。"""
    import pytest
    from app.modules.shared.kueue_status import (
        KUEUE_ADMITTED, KUEUE_EVICTED, KUEUE_FINISHED, KUEUE_PODS_READY,
        KUEUE_QUEUED, KUEUE_QUOTA_RESERVED, worst_kueue_status,
    )

    test_cases = [
        (KUEUE_PODS_READY, KUEUE_PODS_READY, KUEUE_PODS_READY),
        (KUEUE_QUEUED, KUEUE_ADMITTED, KUEUE_QUEUED),
        (KUEUE_FINISHED, KUEUE_ADMITTED, KUEUE_ADMITTED),
        (KUEUE_EVICTED, KUEUE_ADMITTED, KUEUE_EVICTED),
        (KUEUE_QUOTA_RESERVED, KUEUE_ADMITTED, KUEUE_QUOTA_RESERVED),
        (KUEUE_FINISHED, KUEUE_FINISHED, KUEUE_FINISHED),
        (KUEUE_ADMITTED, KUEUE_QUEUED, KUEUE_QUEUED),
    ]

    for a, b, want in test_cases:
        assert worst_kueue_status(a, b) == want, f"worst_kueue_status({a}, {b}) should be {want}"


def test_worst_kueue_status_none_gateway():
    """None 处理: 任一为 None 时回落已知值; 都 None → None。"""
    from app.modules.shared.kueue_status import (
        KUEUE_ADMITTED, worst_kueue_status,
    )
    assert worst_kueue_status(KUEUE_ADMITTED, None) == KUEUE_ADMITTED
    assert worst_kueue_status(None, KUEUE_ADMITTED) == KUEUE_ADMITTED
    assert worst_kueue_status(None, None) is None


def test_worst_kueue_status_unknown_string():
    """未知状态 (老数据/legacy) 视为无约束, 回落已知值。"""
    from app.modules.shared.kueue_status import (
        KUEUE_QUEUED, worst_kueue_status,
    )
    assert worst_kueue_status("started", KUEUE_QUEUED) == KUEUE_QUEUED
