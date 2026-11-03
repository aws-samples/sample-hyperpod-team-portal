"""Monitoring · domain 层单测 (纯函数).

覆盖:
    - subst_template 变量替换正确
    - PromQL 模板列表非空且字段完整
    - 向后兼容 shim 仍然 import 可用
"""

from __future__ import annotations

from app.core import i18n
from app.modules.monitoring.api.schemas import QueryTemplate
from app.modules.monitoring.domain import promql as promql_domain
from app.modules.monitoring.domain.template_subst import subst_template


def test_subst_template_replaces_all_vars() -> None:
    tpl = QueryTemplate(
        key="gpu_util",
        title="GPU 利用率",
        unit="%",
        category="gpu",
        promql='DCGM_FI_DEV_GPU_UTIL{Hostname=~"$node_regex",ns="$namespace"}',
    )
    out = subst_template(tpl, node_regex="h-1|h-2", namespace="ns-a")
    assert "$node_regex" not in out.promql
    assert "$namespace" not in out.promql
    assert "h-1|h-2" in out.promql
    assert "ns-a" in out.promql
    # Original must not be mutated (immutability principle).
    assert "$node_regex" in tpl.promql


def test_subst_template_ignores_missing_vars() -> None:
    tpl = QueryTemplate(
        key="t",
        title="t",
        unit="%",
        category="gpu",
        promql='x{pod="$pod_regex"}',
    )
    out = subst_template(tpl, namespace="foo")  # pod_regex not provided
    assert out.promql == 'x{pod="$pod_regex"}'


def test_promql_template_lists_nonempty() -> None:
    # Training / DevInstance / KPI all must be populated;
    # exact counts evolve with the spec (14/4/3 is current target).
    assert len(promql_domain.TRAINING_TEMPLATES) >= 10
    assert len(promql_domain.DEV_INSTANCE_TEMPLATES) >= 3
    assert len(promql_domain.DEV_INSTANCE_KPI_TEMPLATES) >= 3


def test_promql_templates_have_required_fields() -> None:
    for tpl in (
        promql_domain.TRAINING_TEMPLATES
        + promql_domain.DEV_INSTANCE_TEMPLATES
        + promql_domain.DEV_INSTANCE_KPI_TEMPLATES
    ):
        assert tpl.key
        assert i18n.has(f"monitoring.tpl.{tpl.key}.title", "zh-CN")
        assert tpl.promql
        assert tpl.category in {
            "gpu", "cpu", "memory", "disk", "network", "training", "inference",
            "status", "event", "mlflow", "efa", "fsx", "process",
        }


def test_dev_instance_templates_dimension_routing() -> None:
    """开发机指标按 pod (pod_regex + namespace) 查, dimension 区分 gpu_card / pod.

    开发机与别的 workload 共节点, 故 DCGM GPU 指标必须按 **pod** 精确定位本开发机
    占用的卡 (实测 DCGM 指标确有 pod label), 不能按 node — 否则串到同节点别人的卡。
    (推理独占节点才按 Hostname/node_regex, 见 INFERENCE_TEMPLATES。)

    回归保护: 防止开发机模板漏掉 namespace+pod_regex 限定 (会串到全集群指标)。
    """
    gpu_metrics = {"DCGM_FI_DEV_"}
    for tpl in promql_domain.DEV_INSTANCE_TEMPLATES:
        is_dcgm = any(m in tpl.promql for m in gpu_metrics)
        # 开发机所有指标都按 namespace+pod_regex 查 (共节点, 必须 pod 级精确)
        assert "$pod_regex" in tpl.promql, tpl.key
        assert "$namespace" in tpl.promql, tpl.key
        if is_dcgm:
            assert tpl.dimension == "gpu_card", tpl.key
        else:
            assert tpl.dimension == "pod", tpl.key


def test_dev_instance_pod_selector_uses_prefixed_label() -> None:
    """DevInstance pod 选择器必须用带前缀的 operator label.

    回归保护: jupyter operator 实际打的是
    ``workspace.jupyter.org/workspace-name``, 裸 ``workspace-name`` 匹配不到,
    会让 node_regex fallback 成 ``.*`` (全 DCGM 节点) → 开发机 GPU 指标串台.
    """
    import inspect

    from app.modules.monitoring.orchestration import templates as orch

    src = inspect.getsource(orch.resolve_pods_node_regex)
    assert "workspace.jupyter.org/workspace-name=" in src
    # 必须是带前缀的, 不能退回裸 key
    assert 'f"workspace-name=' not in src


def test_rayjob_pod_selector_uses_ray_cluster_label() -> None:
    """回归保护: RayJob pod 选择器必须用 ``ray.io/cluster`` label + RayCluster 名。

    用错 label → node_regex fallback ``.*`` → GPU 指标串台。
    """
    import inspect

    from app.modules.monitoring.orchestration import templates as orch

    assert "ray.io/cluster=" in inspect.getsource(orch.resolve_pods_node_regex)
    # resolver 空 ray_cluster_name 直接返 [] (未 sync 无锚点), 不瞎查
    assert "if not ray_cluster_name:" in inspect.getsource(
        orch.resolve_rayjob_templates
    )


def test_backward_compat_shim_still_works() -> None:
    """旧 import path 必须继续可用."""
    from app.modules.monitoring import promql, schemas, service

    assert promql.TRAINING_TEMPLATES is promql_domain.TRAINING_TEMPLATES
    assert schemas.QueryTemplate is QueryTemplate
    # service shim 暴露 PromAPIError / instant_query / range_query
    assert hasattr(service, "PromAPIError")
    assert hasattr(service, "instant_query")
    assert hasattr(service, "range_query")
