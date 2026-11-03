"""derive_inference_phase 纯函数测试 (推理 CR status → phase)。"""
from app.modules.inference.domain.phase import derive_inference_phase


def _cr(conditions=None, deploy_overall=None, deploy_available=False,
        ready_replicas=0, state=None, phase=None):
    status = {}
    if conditions is not None:
        status["conditions"] = conditions
    if deploy_overall or deploy_available or ready_replicas:
        status["deploymentStatus"] = {
            "deploymentObjectOverallState": deploy_overall,
            "status": {
                "conditions": [
                    {"type": "Available",
                     "status": "True" if deploy_available else "False"}
                ],
                "readyReplicas": ready_replicas,
            },
        }
    if state:
        status["state"] = state
    if phase:
        status["phase"] = phase
    return {"status": status}


def test_failed_by_condition():
    assert derive_inference_phase(
        _cr(conditions=[{"type": "Failed", "status": "True"}])
    ) == "Failed"


def test_failed_by_deployment_failed():
    assert derive_inference_phase(
        _cr(conditions=[{"type": "DeploymentFailed", "status": "True"}])
    ) == "Failed"


def test_running_by_available_condition():
    assert derive_inference_phase(
        _cr(conditions=[{"type": "Available", "status": "True"}])
    ) == "Running"


def test_running_by_deployment_complete():
    assert derive_inference_phase(
        _cr(deploy_overall="DeploymentComplete", deploy_available=True, ready_replicas=1)
    ) == "Running"


def test_provisioning_by_condition():
    assert derive_inference_phase(
        _cr(conditions=[{"type": "Provisioning", "status": "True"}])
    ) == "Provisioning"


def test_provisioning_by_deployment_inprogress():
    assert derive_inference_phase(
        _cr(deploy_overall="DeploymentInProgress")
    ) == "Provisioning"


def test_pending_fallback():
    assert derive_inference_phase(_cr()) == "Pending"


def test_pending_from_status_phase():
    assert derive_inference_phase(_cr(phase="Pending")) == "Pending"
