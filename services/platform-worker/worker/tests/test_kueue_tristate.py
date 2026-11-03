"""训练 kueue_status 三态 (纯 CR, 不查 Pod)。"""
from worker.phase import derive_train_kueue_status


def _cr(conds):
    return {"status": {"conditions": conds}}


def test_complete_finished():
    assert derive_train_kueue_status(_cr([{"type": "Complete", "status": "True"}])) == "finished"


def test_failed_finished():
    assert derive_train_kueue_status(
        _cr([{"type": "Created", "status": "True"}, {"type": "Failed", "status": "True"}])
    ) == "finished"


def test_completed_variant_finished():
    # 终态 type 文档不一致 (Complete vs Completed); 子串匹配兼容两者
    assert derive_train_kueue_status(_cr([{"type": "Completed", "status": "True"}])) == "finished"


def test_suspended_queued():
    assert derive_train_kueue_status(_cr([{"type": "Suspended", "status": "True"}])) == "queued"


def test_suspended_but_running_is_started():
    assert derive_train_kueue_status(
        _cr([{"type": "Suspended", "status": "True"}, {"type": "Running", "status": "True"}])
    ) == "started"


def test_created_running_started():
    assert derive_train_kueue_status(
        _cr([{"type": "Created", "status": "True"}, {"type": "Running", "status": "True"}])
    ) == "started"


def test_empty_queued():
    assert derive_train_kueue_status(_cr([])) == "queued"
