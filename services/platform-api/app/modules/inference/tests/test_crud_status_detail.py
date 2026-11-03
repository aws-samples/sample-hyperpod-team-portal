"""推理 status_detail 写入对称性: sync 算出后必须能落库 (回归测试)。

根因: _ri_to_inf 读出 status_detail, 但 _inf_to_md (写入侧) 漏了它 →
crud.update 整行 PutItem 时 status_detail 被丢 → DDB 永远没有 → 前端弹窗空。
"""
from app.modules.inference.persistence import crud


def test_inf_to_md_includes_status_detail():
    """_inf_to_md 必须把 status_detail 写进 metadata, 否则 update 整行 put 丢失它。"""
    inf = {
        "name": "ep1",
        "phase": "DeploymentComplete",
        "status_detail": {
            "state": "DeploymentComplete",
            "conditions": [{"type": "Available", "status": "True"}],
            "deploymentStatus": {"deploymentObjectOverallState": "DeploymentComplete"},
        },
    }
    md = crud._inf_to_md(inf)
    assert md["status_detail"] == inf["status_detail"]


def test_ri_to_inf_roundtrip_status_detail():
    """写入 (_inf_to_md) → 读出 (_ri_to_inf) 往返保真。"""
    detail = {"state": "DeploymentFailed", "conditions": [], "deploymentStatus": {}}
    inf = {"name": "ep2", "phase": "DeploymentFailed", "status_detail": detail}
    item = {
        "resource_id": "i2",
        "workspace_id": "ws-1",
        "metadata": crud._inf_to_md(inf),
    }
    out = crud._ri_to_inf(item)
    assert out["status_detail"] == detail
