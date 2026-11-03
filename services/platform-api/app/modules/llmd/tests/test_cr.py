"""llmd domain/cr.py 单测 (分支B)。验必写配方 + 参数化 + 边界。"""

from __future__ import annotations

import pytest

from app.modules.llmd.domain import cr


_DEFAULT_SCRIPT = (
    "exec python3 -m sglang.launch_server "
    "--model-path /model/qwen2.5-0.5b "
    "--dist-init-addr $LWS_LEADER_ADDRESS:20000 "
    "--nnodes $LWS_GROUP_SIZE --node-rank $LWS_WORKER_INDEX "
    "--host 0.0.0.0 --port 8000 --enable-metrics"
)


def _render(**over):
    kw = dict(
        name="llmd-x", namespace="ns-a", llmd_id="id1", workspace_id="ws1", creator_id="u1",
        launch_script=_DEFAULT_SCRIPT,
        model_pvc="pvc-x", gpu_instance_type="ml.g6.12xlarge",
        gateway_instance_type="ml.m5.2xlarge",
        otel_endpoint="otel:4317", otel_image="otel:img",
        nodes_per_replica=2,
    )
    kw.update(over)
    return cr.render_llmd_resources(**kw)


def _by_kind(res, kind, name=None):
    for r in res:
        if r["kind"] == kind and (name is None or r["metadata"]["name"] == name):
            return r
    return None


def _leader_spec(res):
    lws = _by_kind(res, "LeaderWorkerSet")
    return lws["spec"]["leaderWorkerTemplate"]["leaderTemplate"]["spec"]


def _leader_args(res):
    return _leader_spec(res)["containers"][0]["args"]


def test_size1_raises():
    with pytest.raises(ValueError, match="nodes_per_replica"):
        _render(nodes_per_replica=1)


def test_size2_ok():
    lws = _by_kind(_render(nodes_per_replica=2), "LeaderWorkerSet")
    assert lws["spec"]["leaderWorkerTemplate"]["size"] == 2


def test_resource_set():
    kinds = sorted(r["kind"] for r in _render())
    assert kinds == ["ConfigMap", "Deployment", "LeaderWorkerSet",
                     "Role", "RoleBinding", "Service", "ServiceAccount"]


def test_gateway_rbac():
    res = _render()
    sa = _by_kind(res, "ServiceAccount")
    role = _by_kind(res, "Role")
    assert sa["metadata"]["name"] == "llmd-x-gateway-sa"
    assert role["rules"][0]["resources"] == ["pods"]
    assert "list" in role["rules"][0]["verbs"]
    dep = _by_kind(res, "Deployment")
    assert dep["spec"]["template"]["spec"]["serviceAccountName"] == "llmd-x-gateway-sa"


def test_gateway_probe_paths():
    # 不能同路径: readiness 用浅端点会漏摘, liveness 用深端点会错杀
    c = _by_kind(_render(), "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert c["readinessProbe"]["httpGet"]["path"] == "/readiness"
    assert c["livenessProbe"]["httpGet"]["path"] == "/health"


def test_no_ingress_by_default():
    assert "Ingress" not in [r["kind"] for r in _render()]


def test_ingress_rendered_when_exposed():
    ing = _by_kind(_render(expose_alb=True), "Ingress")
    a = ing["metadata"]["annotations"]
    assert ing["metadata"]["name"] == "alb-llmd-x"        # sync 靠这个名字回读
    assert ing["spec"]["ingressClassName"] == "alb"        # controller 靠它认领
    assert a["alb.ingress.kubernetes.io/listen-ports"] == '[{"HTTP":80}]'
    assert a["alb.ingress.kubernetes.io/target-type"] == "ip"          # HyperPod 硬要求
    assert a["alb.ingress.kubernetes.io/healthcheck-path"] == "/readiness"
    assert a["alb.ingress.kubernetes.io/scheme"] == "internal"
    # 不挂证书 (改回 TLS 时这条会红, 是刻意的)
    assert "alb.ingress.kubernetes.io/certificate-arn" not in a


def test_ingress_carries_platform_labels():
    # Go controller 按 llmd-id label List; 漏打则它看不到 Ingress 且不报错。
    # Python sync 按名字 get, 测不出来, 故在此钉住。
    lb = _by_kind(_render(expose_alb=True), "Ingress")["metadata"]["labels"]
    assert lb["platform.hyperpod.io/llmd-id"] == "id1"
    assert lb["app.kubernetes.io/instance"] == "llmd-x"


def test_ingress_backend_points_to_gateway_svc():
    ing = _by_kind(_render(expose_alb=True), "Ingress")
    p = ing["spec"]["rules"][0]["http"]["paths"][0]
    svc = p["backend"]["service"]
    assert (svc["name"], svc["port"]["number"]) == ("llmd-x-gateway", 30000)
    assert (p["path"], p["pathType"]) == ("/", "Prefix")   # 不限单端点


def test_queue_name_top_only_on_lws():
    lws = _by_kind(_render(), "LeaderWorkerSet")
    assert lws["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == "ns-a-localqueue"
    lt = lws["spec"]["leaderWorkerTemplate"]["leaderTemplate"]["metadata"]["labels"]
    assert "kueue.x-k8s.io/queue-name" not in lt


def test_pool_label_matches_gateway_selector():
    res = _render()
    lt = _by_kind(res, "LeaderWorkerSet")["spec"]["leaderWorkerTemplate"]["leaderTemplate"]["metadata"]["labels"]
    assert lt["llmd.sgl/pool"] == "llmd-x"
    dep_args = _by_kind(res, "Deployment")["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "llmd.sgl/pool=llmd-x" in dep_args


def test_platform_labels():
    lb = _by_kind(_render(), "LeaderWorkerSet")["metadata"]["labels"]
    assert lb["platform.hyperpod.io/llmd-id"] == "id1"
    assert lb["platform.hyperpod.io/workspace-id"] == "ws1"


def test_launch_script_as_sh_c():
    # 用户整段脚本经 /bin/sh -c 跑: command=[/bin/sh,-c], args=[脚本单元素]
    leader = _leader_spec(_render())["containers"][0]
    assert leader["command"] == ["/bin/sh", "-c"]
    assert leader["args"] == [_DEFAULT_SCRIPT]


def test_efa_conditional():
    req0 = _leader_spec(_render(efa_per_pod=0))["containers"][0]["resources"]["requests"]
    assert "vpc.amazonaws.com/efa" not in req0
    req8 = _leader_spec(_render(efa_per_pod=8))["containers"][0]["resources"]["requests"]
    assert req8["vpc.amazonaws.com/efa"] == "8"


def test_lws_placeholders_shell_form():
    # sh -c 下 LWS 占位符必须 shell 形式 $LWS_* (非 $(LWS_*) 命令替换会挂)
    script = _leader_args(_render())[0]
    assert "$LWS_LEADER_ADDRESS" in script
    assert "$LWS_GROUP_SIZE" in script
    assert "$LWS_WORKER_INDEX" in script
    assert "$(LWS_" not in script


def test_podantiaffinity():
    term = _leader_spec(_render())["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][0]
    assert term["topologyKey"] == "kubernetes.io/hostname"


def test_otel_configmap():
    cm = _by_kind(_render(), "ConfigMap")
    assert cm["metadata"]["name"] == "llmd-x-otel"
    assert "gateway.yaml" in cm["data"] and "worker.yaml" in cm["data"]
    assert "otel:4317" in cm["data"]["gateway.yaml"]


def test_leader_http_worker_no():
    lws = _by_kind(_render(), "LeaderWorkerSet")
    lp = [p["name"] for p in lws["spec"]["leaderWorkerTemplate"]["leaderTemplate"]["spec"]["containers"][0]["ports"]]
    wp = [p["name"] for p in lws["spec"]["leaderWorkerTemplate"]["workerTemplate"]["spec"]["containers"][0]["ports"]]
    assert "http" in lp
    assert "http" not in wp
