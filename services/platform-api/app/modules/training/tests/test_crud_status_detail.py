"""训练 status_detail 写入对称性回归测试。

根因 (同推理): _ri_to_job 读出 status_detail, 但 _job_to_md (写入侧) 一旦漏了它 →
create 走 upsert_resource 整行 PutItem 时丢失它 → DDB 无 status_detail。
故 _job_to_md / _ri_to_job 往返必须保真。
(原 crud.update 死代码已删 — informer 直写状态, training 无 sync, 。)
"""
from app.modules.training.persistence import crud


def test_job_to_md_includes_status_detail():
    """_job_to_md 必须把 status_detail 写进 metadata, 否则整行 put 丢失。"""
    job = {
        "name": "job1",
        "phase": "Created/Running",
        "status_detail": {"conditions": [{"type": "Running", "status": "True"}]},
    }
    md = crud._job_to_md(job)
    assert md["status_detail"] == job["status_detail"]


def test_ri_to_job_roundtrip_status_detail():
    """写入 (_job_to_md) → 读出 (_ri_to_job) 往返保真。"""
    detail = {"conditions": [{"type": "Complete", "status": "True"}], "completionTime": "t"}
    job = {"name": "job2", "phase": "Complete", "status_detail": detail}
    item = {
        "resource_id": "t2",
        "workspace_id": "ws-1",
        "metadata": crud._job_to_md(job),
    }
    out = crud._ri_to_job(item)
    assert out["status_detail"] == detail
