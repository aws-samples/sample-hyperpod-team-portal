"""DynamoGraphDeployment CR 渲染器单测 (纯函数, 无 IO)."""

from __future__ import annotations

from app.modules.dynamo.domain.cr import (
    DYNAMO_API_VERSION,
    DYNAMO_KIND,
    otel_configmap_name,
    render_dynamo_graph_deployment_cr,
    render_dynamo_otel_config,
)

_SCRIPT = (
    "exec python3 -m dynamo.sglang --model-path /fsx/models/qwen "
    "--served-model-name qwen --tp-size 2 --ep-size 2 --host 0.0.0.0"
)

_BASE = dict(
    name="dyn-abc",
    namespace="hyperpod-ns-demo",
    dynamo_id="d-123",
    workspace_id="ws-1",
    creator_id="alice@example.com",
    fsx_pvc_name="pvc-ws-fsx-teamdata-rw",
    launch_script=_SCRIPT,
    instance_type="ml.g6.12xlarge",
)


def test_apiversion_kind():
    cr = render_dynamo_graph_deployment_cr(**_BASE)
    assert cr["apiVersion"] == DYNAMO_API_VERSION
    assert cr["kind"] == DYNAMO_KIND
    assert cr["metadata"]["name"] == "dyn-abc"
    assert cr["metadata"]["namespace"] == "hyperpod-ns-demo"


def test_platform_label_contract():
    """★ Go controller 契约: dynamo-id / workspace-id label 必须存在且值对。"""
    cr = render_dynamo_graph_deployment_cr(**_BASE)
    labels = cr["metadata"]["labels"]
    assert labels["platform.hyperpod.io/dynamo-id"] == "d-123"
    assert labels["platform.hyperpod.io/workspace-id"] == "ws-1"
    assert "@" not in labels["platform.hyperpod.io/creator-id"]
    assert labels["kueue.x-k8s.io/queue-name"] == "hyperpod-ns-demo-localqueue"


def test_components_frontend_and_worker():
    cr = render_dynamo_graph_deployment_cr(**_BASE)
    names = {c["name"]: c for c in cr["spec"]["components"]}
    assert set(names) == {"Frontend", "worker"}
    assert names["Frontend"]["type"] == "frontend"
    assert names["worker"]["type"] == "worker"


def test_single_node_no_multinode():
    cr = render_dynamo_graph_deployment_cr(**_BASE, node_count=1)
    worker = next(c for c in cr["spec"]["components"] if c["name"] == "worker")
    assert "multinode" not in worker


def test_multinode_renders_nodecount():
    cr = render_dynamo_graph_deployment_cr(**_BASE, node_count=3)
    worker = next(c for c in cr["spec"]["components"] if c["name"] == "worker")
    assert worker["multinode"]["nodeCount"] == 3


def test_launch_script_into_args():
    cr = render_dynamo_graph_deployment_cr(**_BASE)
    worker = next(c for c in cr["spec"]["components"] if c["name"] == "worker")
    main = worker["podTemplate"]["spec"]["containers"][0]
    assert main["command"] == ["/bin/sh", "-c"]
    assert main["args"] == [_SCRIPT]


def test_fsx_pvc_mounted():
    """授权反查出的 pvc_name 挂进 worker + frontend。"""
    cr = render_dynamo_graph_deployment_cr(**_BASE)
    worker = next(c for c in cr["spec"]["components"] if c["name"] == "worker")
    vols = {v["name"]: v for v in worker["podTemplate"]["spec"]["volumes"]}
    assert vols["fsx"]["persistentVolumeClaim"]["claimName"] == "pvc-ws-fsx-teamdata-rw"
    assert "dshm" in vols


def test_fsx_mount_path_follows_mount():
    """★挂载点用 mount_path (与开发机/推理一致), 非硬编码 /fsx (踩坑修复)。"""
    cr = render_dynamo_graph_deployment_cr(**_BASE, fsx_mount_path="/fsx/team-a-data")
    for comp in cr["spec"]["components"]:
        main = comp["podTemplate"]["spec"]["containers"][0]
        mounts = {m["name"]: m for m in main["volumeMounts"]}
        assert mounts["fsx"]["mountPath"] == "/fsx/team-a-data"
    # 默认兜底 /fsx
    cr2 = render_dynamo_graph_deployment_cr(**_BASE)
    w2 = next(c for c in cr2["spec"]["components"] if c["name"] == "worker")
    m2 = {m["name"]: m for m in w2["podTemplate"]["spec"]["containers"][0]["volumeMounts"]}
    assert m2["fsx"]["mountPath"] == "/fsx"


def test_resources_from_template():
    cr = render_dynamo_graph_deployment_cr(
        **_BASE,
        gpu_per_worker=4,
        cpu_request_millicores=8000,
        cpu_limit_millicores=16000,
        memory_request_mib=65536,
        memory_limit_mib=131072,
        efa_per_worker=1,
    )
    worker = next(c for c in cr["spec"]["components"] if c["name"] == "worker")
    res = worker["podTemplate"]["spec"]["containers"][0]["resources"]
    assert res["requests"]["nvidia.com/gpu"] == "4"
    assert res["requests"]["cpu"] == "8000m"
    assert res["limits"]["cpu"] == "16000m"
    assert res["limits"]["memory"] == "131072Mi"
    assert res["limits"]["vpc.amazonaws.com/efa"] == "1"


def test_run_as_root_security_context():
    """★ frontend + worker 都要 root (都读 FSx 模型路径); frontend 漏了 → /v1/models 空。"""
    cr = render_dynamo_graph_deployment_cr(**_BASE)
    for comp in cr["spec"]["components"]:
        sc = comp["podTemplate"]["spec"]["securityContext"]
        assert sc["runAsUser"] == 0
        assert sc["runAsGroup"] == 0
    cr2 = render_dynamo_graph_deployment_cr(**_BASE, run_as_root=False)
    for comp in cr2["spec"]["components"]:
        assert "securityContext" not in comp["podTemplate"]["spec"]


def test_otel_sidecar_added_when_metrics_enabled():
    """★ metrics_enabled: frontend + worker 各加 otel-collector sidecar + configmap volume。"""
    cr = render_dynamo_graph_deployment_cr(**_BASE)  # 默认 metrics_enabled=True
    for comp in cr["spec"]["components"]:
        spec = comp["podTemplate"]["spec"]
        names = {c["name"] for c in spec["containers"]}
        assert "otel-collector" in names, comp["name"]
        vols = {v["name"] for v in spec["volumes"]}
        assert "otel-cfg" in vols
        otel = next(c for c in spec["containers"] if c["name"] == "otel-collector")
        assert otel["args"] == ["--config=/etc/otel/config.yaml"]
    # 关掉则不加
    cr2 = render_dynamo_graph_deployment_cr(**_BASE, metrics_enabled=False)
    for comp in cr2["spec"]["components"]:
        names = {c["name"] for c in comp["podTemplate"]["spec"]["containers"]}
        assert "otel-collector" not in names


def test_otel_config_and_name():
    """otel configmap 名 + config 内容 (scrape localhost:9090/8000 → 推中央 collector)。"""
    assert otel_configmap_name("dyn-abc") == "dynamo-dyn-abc-otel"
    cfg = render_dynamo_otel_config("dyn-abc", "hyperpod-ns-demo")
    assert "localhost:9090" in cfg
    assert "localhost:8000" in cfg
    assert "hyperpod-otel-collector.hyperpod-observability:4317" in cfg
    assert "resource_name: 'dyn-abc'" in cfg
