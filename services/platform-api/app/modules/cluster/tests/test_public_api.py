"""模块公共导入 smoke test

职责:
- 验证 `from app.modules.cluster import crud, cluster_router` 可用
- 验证 crud 暴露的跨模块 API 完整
- 验证不小心破坏 orchestration/domain/persistence 子包导入路径时测试立刻 FAIL
"""

from __future__ import annotations

import inspect

import pytest


def test_top_level_exports() -> None:
    """外部调用方的契约: `from app.modules.cluster import crud, cluster_router`"""
    from app.modules.cluster import cluster_router, crud

    assert crud is not None
    assert cluster_router is not None


def test_crud_public_contract() -> None:
    """跨模块要求的最小 CRUD 接口

    对外使用者（workspace/logs/quota）依赖:
    - get_cluster_by_id(db, id) → Cluster | None
    - get_cluster_by_tag(db, tag) → Cluster | None
    - list_clusters(db, type_filter=None) → list[Cluster]
    - list_instance_groups(db, cluster_id) → list[InstanceGroup]
    """
    from app.modules.cluster import crud

    for name in (
        "get_cluster_by_id",
        "get_cluster_by_tag",
        "list_clusters",
        "list_instance_groups",
        "count_nodes_by_health",
        "get_cluster_summary_aggregated",
        "list_resource_quotas",
        "log_node_operation",
    ):
        fn = getattr(crud, name, None)
        assert fn is not None, f"crud.{name} 必须保留，跨模块调用依赖"
        assert inspect.iscoroutinefunction(fn), f"crud.{name} 应为 async"


def test_orchestration_public_contract() -> None:
    """orchestration 入口函数（未来 M2 / monitoring 模块可调）"""
    from app.modules.cluster import orchestration

    for name in (
        "reboot_node",
        "replace_node",
        "delete_node",
        "describe_cluster_live",
        "list_cluster_nodes_live",
        "list_k8s_nodes",
    ):
        assert getattr(orchestration, name, None) is not None, (
            f"orchestration.{name} 必须导出"
        )


def test_domain_modules_importable() -> None:
    """domain 层纯函数独立可 import（禁止引入 IO 依赖）"""
    from app.modules.cluster.domain import capacity, health_check

    assert callable(health_check.derive_health_status)
    assert callable(capacity.gpu_usage_pct)


def test_response_builders_importable() -> None:
    """response 层纯函数"""
    from app.modules.cluster.response import builders

    assert callable(builders.build_quota_flat)
    assert callable(builders.build_quotas_tree)
    assert callable(builders.build_cluster_info)


def test_router_paths() -> None:
    """HTTP 路由硬约束：/clusters 下必保留 4 条现有端点

    - GET /               list
    - GET /{tag}          detail
    - POST /{tag}/sync    sync
    - GET /{tag}/summary  summary
    """
    from app.modules.cluster import cluster_router

    paths_methods = {
        (route.path, method)
        for route in cluster_router.routes
        for method in getattr(route, "methods", set())
    }

    assert ("", "GET") in paths_methods or ("/", "GET") in paths_methods
    assert ("/{cluster_tag}", "GET") in paths_methods
    assert ("/{cluster_tag}/sync", "POST") in paths_methods
    assert ("/{cluster_tag}/summary", "GET") in paths_methods


def test_no_legacy_flat_modules() -> None:
    """旧的扁平六件套必须已经删除（资产导向重构完成）

    app/modules/cluster/models.py / crud.py / router.py / service.py /
    sync_service.py / schemas.py 不应再存在。
    """
    import importlib.util

    for legacy in (
        "app.modules.cluster.models",
        "app.modules.cluster.crud",
        "app.modules.cluster.router",
        "app.modules.cluster.service",
        "app.modules.cluster.sync_service",
        "app.modules.cluster.schemas",
    ):
        spec = importlib.util.find_spec(legacy)
        assert spec is None, f"旧扁平模块 {legacy} 未删除，资产导向重构未完成"


def test_node_module_removed() -> None:
    """modules/node/ 空壳必须已吞并到 cluster"""
    import importlib.util

    spec = importlib.util.find_spec("app.modules.node")
    assert spec is None, "app/modules/node 应删除，已并入 cluster"


def test_instance_groups_route_has_admin_and_path_param():
    """回归: instance-groups 端点必须绑在真正的 endpoint 上 (带 {cluster_tag} 路径参数 + require_admin),
    不能被 helper 抢占 decorator。"""
    from app.modules.cluster import cluster_router

    route = next(
        r for r in cluster_router.routes
        if getattr(r, "path", None) == "/{cluster_tag}/instance-groups"
    )
    # 路径参数必须存在 (endpoint 有 cluster_tag, 而非 helper 的 cluster_name 查询参)
    assert route.endpoint.__name__ == "list_instance_groups_endpoint"
    assert "cluster_tag" in route.param_convertors
    # require_admin 依赖必须在
    assert len(route.dependant.dependencies) >= 1


@pytest.mark.asyncio
async def test_instance_groups_enriched_with_specs(monkeypatch):
    from app.modules.cluster.api import router as r
    from app.adapters.aws.ec2_instance_types import InstanceSpec

    async def fake_list(name):
        return [
            {"InstanceGroupName": "g1", "InstanceType": "ml.g6.12xlarge", "CurrentCount": 2},
            {"InstanceGroupName": "c1", "InstanceType": "ml.c5.2xlarge", "CurrentCount": 1},
        ]

    async def fake_specs(types):
        return {
            "ml.g6.12xlarge": InstanceSpec(gpu_count=4, gpu_spec="4×L4", gpu_type="L4", vcpu=48, memory_gib=192.0),
            "ml.c5.2xlarge": InstanceSpec(gpu_count=0, gpu_spec=None, gpu_type=None, vcpu=8, memory_gib=16.0),
        }

    monkeypatch.setattr(r.cluster_describe, "list_instance_groups", fake_list)
    monkeypatch.setattr(r, "get_instance_specs", fake_specs)

    out = await r._enrich_instance_groups_with_specs("cluster-x")
    g = next(x for x in out if x["InstanceType"] == "ml.g6.12xlarge")
    assert g["gpu_count"] == 4
    assert g["gpu_type"] == "L4"
    assert g["gpu_spec"] == "4×L4"
    assert g["vcpu"] == 48
    assert g["memory_gib"] == 192.0
    c = next(x for x in out if x["InstanceType"] == "ml.c5.2xlarge")
    assert c["gpu_count"] == 0
    assert c["gpu_type"] is None
