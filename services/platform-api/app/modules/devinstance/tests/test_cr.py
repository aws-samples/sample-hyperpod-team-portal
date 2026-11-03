"""render_workspace_cr nodeAffinity 机型锁定测试。"""
from app.modules.devinstance.domain.cr import render_workspace_cr


def _required_match_exprs(cr):
    """取 required nodeAffinity 第一个 term 的 matchExpressions。"""
    aff = cr["spec"]["affinity"]["nodeAffinity"]
    term = aff["requiredDuringSchedulingIgnoredDuringExecution"][
        "nodeSelectorTerms"
    ][0]
    return term["matchExpressions"]


def test_no_instance_type_only_health_filter():
    cr = render_workspace_cr(name="dev1", display_name="dev1")
    exprs = _required_match_exprs(cr)
    keys = [m["key"] for m in exprs]
    assert keys == ["sagemaker.amazonaws.com/node-health-status"]


def test_instance_type_adds_matchexpression():
    cr = render_workspace_cr(
        name="dev1", display_name="dev1", instance_type="ml.g6.12xlarge"
    )
    exprs = _required_match_exprs(cr)
    keys = [m["key"] for m in exprs]
    assert "sagemaker.amazonaws.com/node-health-status" in keys
    assert "node.kubernetes.io/instance-type" in keys
    it_expr = next(
        m for m in exprs if m["key"] == "node.kubernetes.io/instance-type"
    )
    assert it_expr["operator"] == "In"
    assert it_expr["values"] == ["ml.g6.12xlarge"]


def test_instance_types_list_adds_in_expression():
    cr = render_workspace_cr(
        name="dev1", display_name="dev1",
        instance_types=["ml.c5.2xlarge", "ml.c5.4xlarge", "ml.m5.2xlarge"],
    )
    exprs = _required_match_exprs(cr)
    itype = next(
        e for e in exprs if e["key"] == "node.kubernetes.io/instance-type"
    )
    assert itype["operator"] == "In"
    assert itype["values"] == ["ml.c5.2xlarge", "ml.c5.4xlarge", "ml.m5.2xlarge"]


def test_instance_types_empty_list_no_expression():
    cr = render_workspace_cr(name="dev1", display_name="dev1", instance_types=[])
    keys = [e["key"] for e in _required_match_exprs(cr)]
    assert "node.kubernetes.io/instance-type" not in keys


def test_single_instance_type_still_works():
    # 向后兼容: 老调用方传单值
    cr = render_workspace_cr(
        name="dev1", display_name="dev1", instance_type="ml.g6.12xlarge"
    )
    exprs = _required_match_exprs(cr)
    itype = next(
        e for e in exprs if e["key"] == "node.kubernetes.io/instance-type"
    )
    assert itype["values"] == ["ml.g6.12xlarge"]


# ===== EFA (vpc.amazonaws.com/efa) 下发 =====

def test_no_efa_by_default():
    cr = render_workspace_cr(name="dev1", display_name="dev1")
    res = cr["spec"]["resources"]
    assert "vpc.amazonaws.com/efa" not in res["requests"]
    assert "vpc.amazonaws.com/efa" not in res["limits"]


def test_efa_zero_not_rendered():
    cr = render_workspace_cr(name="dev1", display_name="dev1", efa_count=0)
    res = cr["spec"]["resources"]
    assert "vpc.amazonaws.com/efa" not in res["requests"]
    assert "vpc.amazonaws.com/efa" not in res["limits"]


def test_efa_positive_rendered_requests_and_limits():
    cr = render_workspace_cr(
        name="dev1", display_name="dev1", gpu_count=4, efa_count=2
    )
    res = cr["spec"]["resources"]
    assert res["requests"]["vpc.amazonaws.com/efa"] == "2"
    assert res["limits"]["vpc.amazonaws.com/efa"] == "2"
    # 与 GPU 并存, 互不影响
    assert res["requests"]["nvidia.com/gpu"] == "4"


def test_efa_without_gpu():
    # EFA 独立于 GPU: gpu_count=0 也能下发 efa
    cr = render_workspace_cr(name="dev1", display_name="dev1", efa_count=1)
    res = cr["spec"]["resources"]
    assert res["requests"]["vpc.amazonaws.com/efa"] == "1"
    assert res["limits"]["vpc.amazonaws.com/efa"] == "1"
    assert "nvidia.com/gpu" not in res["requests"]
