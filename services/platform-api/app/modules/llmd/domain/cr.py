"""llm-d 资源渲染器 (纯函数, 分支B: LWS + sgl-model-gateway)。

一个服务 = 一组 K8s 资源 (OTel CM / gateway RBAC+Deploy+Svc / LWS)。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import t
from app.core.labels import sanitize_label_value
from app.core.priority_defaults import default_priority_class

_PLATFORM_LABEL_PREFIX = "platform.hyperpod.io"
_DEFAULT_SGLANG_IMAGE = "lmsysorg/sglang:v0.5.13.post1"
_DEFAULT_GATEWAY_IMAGE = "lmsysorg/sgl-model-gateway:latest"
_GATEWAY_PORT = 30000
_GATEWAY_METRICS_PORT = 29000
_ENGINE_PORT = 8000
_DIST_PORT = 20000
_MODEL_MOUNT = "/model"

# sgl-model-gateway: /readiness 反映有无可用 worker, /health 只证进程活着
# (没有 /ping, 别照抄 IEC)
_READINESS_PATH = "/readiness"
_LIVENESS_PATH = "/health"

MIN_NODES_PER_REPLICA = 2


def _platform_labels(llmd_id: str, workspace_id: str, creator_id: str) -> dict[str, str]:
    return {
        f"{_PLATFORM_LABEL_PREFIX}/llmd-id": llmd_id,
        f"{_PLATFORM_LABEL_PREFIX}/workspace-id": workspace_id,
        f"{_PLATFORM_LABEL_PREFIX}/creator-id": sanitize_label_value(
            creator_id, fallback="unknown"
        ),
    }


def _otel_configmap(name: str, namespace: str, otel_endpoint: str) -> dict[str, Any]:
    """gateway.yaml + worker.yaml 采集配置 (多行 YAML 字符串, ${POD_NAME}/${NODE_NAME} 运行时注入)。"""
    def _cfg(job: str, source: str, target_port: int, role_label: str) -> str:
        role_line = f"\n                role: {role_label}" if role_label else ""
        return f"""receivers:
  prometheus/{job}:
    config:
      scrape_configs:
        - job_name: llmd-sgl-{job}
          scrape_interval: 15s
          metrics_path: /metrics
          static_configs:
            - targets: ["localhost:{target_port}"]
              labels:
                metric_source: {source}
                resource_name: {name}
                namespace: {namespace}{role_line}
                pod_name: '${{POD_NAME}}'
                node_name: '${{NODE_NAME}}'
exporters:
  otlp/grpc:
    endpoint: "{otel_endpoint}"
    tls:
      insecure: true
    sending_queue:
      enabled: true
      queue_size: 5000
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s
service:
  pipelines:
    metrics:
      receivers: [prometheus/{job}]
      exporters: [otlp/grpc]
  telemetry:
    logs:
      level: warn
"""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"{name}-otel",
            "namespace": namespace,
            "labels": {"app.kubernetes.io/instance": name},
        },
        "data": {
            "gateway.yaml": _cfg("gateway", "sgl-model-gateway", _GATEWAY_METRICS_PORT, ""),
            "worker.yaml": _cfg("worker", "sglang-worker", _ENGINE_PORT, "leader"),
        },
    }


def _otel_sidecar(name: str, otel_image: str, subpath: str) -> dict[str, Any]:
    return {
        "name": f"{subpath.split('.')[0]}-otel-collector",
        "image": otel_image,
        "args": ["--config=/etc/otel/config.yaml"],
        "env": [
            {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
            {"name": "NODE_NAME", "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}}},
        ],
        "resources": {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "100m", "memory": "128Mi"},
        },
        "volumeMounts": [
            {"name": f"{subpath.split('.')[0]}-otel-config",
             "mountPath": "/etc/otel/config.yaml", "subPath": subpath}
        ],
    }


def _gateway_rbac(name: str, namespace: str) -> list[dict[str, Any]]:
    sa_name = f"{name}-gateway-sa"
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount",
         "metadata": {"name": sa_name, "namespace": namespace}},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
         "metadata": {"name": f"{name}-gateway-role", "namespace": namespace},
         "rules": [{"apiGroups": [""], "resources": ["pods"],
                    "verbs": ["get", "list", "watch"]}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
         "metadata": {"name": f"{name}-gateway-rb", "namespace": namespace},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role",
                     "name": f"{name}-gateway-role"},
         "subjects": [{"kind": "ServiceAccount", "name": sa_name, "namespace": namespace}]},
    ]


def _gateway_deployment(
    *, name: str, namespace: str, queue_name: str, gateway_image: str, otel_image: str,
    gateway_instance_type: str, labels: dict[str, str],
    gateway_replicas: int = 1, gateway_extra_args: list[str] | None = None,
    gateway_cpu_request_millicores: int = 1000,
    gateway_cpu_limit_millicores: int = 4000,
    gateway_memory_request_mib: int = 2048,
    gateway_memory_limit_mib: int = 8192,
) -> dict[str, Any]:
    gw_name = f"{name}-gateway"
    sel = {"app.kubernetes.io/name": gw_name}
    # 结构性参数拼死 (改了 gateway 发现不了 worker): 发现机制 + 端口 + metrics。
    # 调优参数 (--policy/--cache-threshold/queue/health-check 等) 全由用户 gateway_extra_args
    # 给 (前端预填默认可编辑, 所见即所得); 后端不再塞调优默认。
    gw_args = [
        "--host=0.0.0.0", f"--port={_GATEWAY_PORT}",
        "--service-discovery", "--selector", f"llmd.sgl/pool={name}",
        f"--service-discovery-namespace={namespace}",
        f"--service-discovery-port={_ENGINE_PORT}",
        "--prometheus-host=0.0.0.0", f"--prometheus-port={_GATEWAY_METRICS_PORT}",
        "--health-check-endpoint=/health",
    ]
    gw_args.extend(gateway_extra_args or [])
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": gw_name, "namespace": namespace,
            "labels": {**labels, **sel, "app.kubernetes.io/instance": name,
                       "kueue.x-k8s.io/queue-name": queue_name,
                       "kueue.x-k8s.io/priority-class": default_priority_class("llmd")},
        },
        "spec": {
            "replicas": gateway_replicas,
            "selector": {"matchLabels": sel},
            "template": {
                # platform labels 透传到 pod (controller 按 llmd-id 圈 gateway pod; 同 LWS pod / 推理/开发机)
                "metadata": {"labels": {**labels, **sel, "app.kubernetes.io/instance": name}},
                "spec": {
                    "serviceAccountName": f"{name}-gateway-sa",
                    # gateway 纯 CPU 路由, 独立选机型 (可落 CPU 池, 不占 GPU 配额)
                    "nodeSelector": {"node.kubernetes.io/instance-type": gateway_instance_type},
                    "containers": [
                        {
                            "name": "gateway", "image": gateway_image,
                            "args": gw_args,
                            "ports": [
                                {"name": "http", "containerPort": _GATEWAY_PORT},
                                {"name": "metrics", "containerPort": _GATEWAY_METRICS_PORT},
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": f"{gateway_cpu_request_millicores}m",
                                    "memory": f"{gateway_memory_request_mib}Mi",
                                },
                                "limits": {
                                    "cpu": f"{gateway_cpu_limit_millicores}m",
                                    "memory": f"{gateway_memory_limit_mib}Mi",
                                },
                            },
                            # 深端点: worker 全挂时才摘出 Endpoints
                            "readinessProbe": {"httpGet": {"path": _READINESS_PATH, "port": "http"},
                                               "periodSeconds": 10},
                            # 浅端点: 用深端点会在 worker 挂时错杀 gateway
                            "livenessProbe": {"httpGet": {"path": _LIVENESS_PATH, "port": "http"},
                                              "periodSeconds": 30},
                        },
                        _otel_sidecar(name, otel_image, "gateway.yaml"),
                    ],
                    "volumes": [
                        {"name": "gateway-otel-config",
                         "configMap": {"name": f"{name}-otel"}},
                    ],
                },
            },
        },
    }


def _gateway_service(name: str, namespace: str) -> dict[str, Any]:
    gw_name = f"{name}-gateway"
    return {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": gw_name, "namespace": namespace},
        "spec": {
            "selector": {"app.kubernetes.io/name": gw_name},
            "ports": [
                {"name": "http", "port": _GATEWAY_PORT, "targetPort": "http"},
                {"name": "metrics", "port": _GATEWAY_METRICS_PORT, "targetPort": "metrics"},
            ],
        },
    }


def _gateway_ingress(
    name: str, namespace: str, *, labels: dict[str, str]
) -> dict[str, Any]:
    """internal ALB Ingress → gateway Service (HTTP:80 明文, 无证书)。

    labels 必须带 platform 那几个: Go controller 的 cache 挂了 llmd-id selector,
    漏打则它 List 不到这个 Ingress 且不报错。
    前置: 节点 SG 放行 tcp 30000 ← ALB 网段, 否则 target 恒 Target.Timeout
    (见 deploy/inference-endpoint-prereq.sh)。
    """
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": f"alb-{name}",          # sync 按这个名字回读
            "namespace": namespace,
            "labels": {**labels, "app.kubernetes.io/instance": name},
            "annotations": {
                "alb.ingress.kubernetes.io/scheme": "internal",
                # 必须 ip: instance 模式下 SageMaker 托管节点注册不进 TG
                "alb.ingress.kubernetes.io/target-type": "ip",
                "alb.ingress.kubernetes.io/listen-ports": '[{"HTTP":80}]',
                "alb.ingress.kubernetes.io/healthcheck-path": _READINESS_PATH,
                "alb.ingress.kubernetes.io/healthcheck-port": "traffic-port",
                "alb.ingress.kubernetes.io/healthcheck-protocol": "HTTP",
                # LLM 请求耗时方差大, 轮询长尾严重
                "alb.ingress.kubernetes.io/target-group-attributes":
                    "load_balancing.algorithm.type=least_outstanding_requests",
                "alb.ingress.kubernetes.io/load-balancer-attributes":
                    "access_logs.s3.enabled=false",
                "alb.ingress.kubernetes.io/tags":
                    "CreatedBy=HyperPodPlatform,Pipeline=llmd",
            },
        },
        "spec": {
            "ingressClassName": "alb",
            "rules": [{"http": {"paths": [{
                "path": "/",
                "pathType": "Prefix",
                "backend": {"service": {
                    "name": f"{name}-gateway",
                    "port": {"number": _GATEWAY_PORT},
                }},
            }]}}],
        },
    }


def _sglang_container(
    *, launch_script: str, gpu_per_pod: int, efa_per_pod: int, is_leader: bool,
    sglang_image: str, model_mount_path: str,
    cpu_request_millicores: int, cpu_limit_millicores: int,
    memory_request_mib: int, memory_limit_mib: int,
) -> dict[str, Any]:
    # 用户整段脚本经 /bin/sh -c 跑; leader/worker 共用同一脚本。脚本里用 shell 形式
    # $LWS_LEADER_ADDRESS / $LWS_GROUP_SIZE / $LWS_WORKER_INDEX (LWS 注入为容器 env,
    # sh 展开)。不能写 $(LWS_*): sh -c 下 $(...) 是命令替换会当命令跑挂。
    ports = [{"name": "dist-init", "containerPort": _DIST_PORT}]
    if is_leader:
        ports.insert(0, {"name": "http", "containerPort": _ENGINE_PORT})
    gpu_req: dict[str, Any] = {
        "nvidia.com/gpu": str(gpu_per_pod),
        "cpu": f"{cpu_request_millicores}m",
        "memory": f"{memory_request_mib}Mi",
    }
    gpu_lim: dict[str, Any] = {
        "nvidia.com/gpu": str(gpu_per_pod),
        "cpu": f"{cpu_limit_millicores}m",
        "memory": f"{memory_limit_mib}Mi",
    }
    if efa_per_pod > 0:
        gpu_req["vpc.amazonaws.com/efa"] = str(efa_per_pod)
        gpu_lim["vpc.amazonaws.com/efa"] = str(efa_per_pod)
    c: dict[str, Any] = {
        "name": "sglang",
        "image": sglang_image,
        "command": ["/bin/sh", "-c"],
        "args": [launch_script],
        "env": [
            {"name": "FI_PROVIDER", "value": "efa"},
            {"name": "NCCL_SOCKET_IFNAME", "value": "eth0"},
            {"name": "GLOO_SOCKET_IFNAME", "value": "eth0"},
        ],
        "ports": ports,
        "resources": {"requests": gpu_req, "limits": gpu_lim},
        "volumeMounts": [
            {"name": "model", "mountPath": model_mount_path, "readOnly": True},
            {"name": "dshm", "mountPath": "/dev/shm"},
        ],
    }
    if is_leader:
        c["startupProbe"] = {"httpGet": {"path": "/health", "port": "http"},
                             "periodSeconds": 15, "failureThreshold": 120, "timeoutSeconds": 10}
        c["readinessProbe"] = {"httpGet": {"path": "/health", "port": "http"},
                               "periodSeconds": 10, "failureThreshold": 3, "timeoutSeconds": 10}
    return c


def _pod_spec(
    *, name: str, gpu_instance_type: str, model_pvc: str, otel_image: str,
    sglang_c: dict[str, Any], otel_subpath: str,
) -> dict[str, Any]:
    return {
        "nodeSelector": {"node.kubernetes.io/instance-type": gpu_instance_type},
        "securityContext": {"runAsUser": 0, "runAsGroup": 0, "supplementalGroups": [5001]},
        "affinity": {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
            {"topologyKey": "kubernetes.io/hostname",
             "labelSelector": {"matchLabels": {"app.kubernetes.io/name": f"{name}-multi"}}}
        ]}},
        "containers": [sglang_c, _otel_sidecar(name, otel_image, otel_subpath)],
        "volumes": [
            {"name": "model", "persistentVolumeClaim": {"claimName": model_pvc}},
            {"name": "dshm", "emptyDir": {"medium": "Memory", "sizeLimit": "32Gi"}},
            {"name": f"{otel_subpath.split('.')[0]}-otel-config",
             "configMap": {"name": f"{name}-otel"}},
        ],
    }


def _leaderworkerset(
    *, name: str, namespace: str, queue_name: str, labels: dict[str, str], otel_image: str,
    replicas: int, nodes_per_replica: int, launch_script: str,
    gpu_per_pod: int, efa_per_pod: int, gpu_instance_type: str,
    model_pvc: str, model_mount_path: str, sglang_image: str,
    cpu_request_millicores: int, cpu_limit_millicores: int,
    memory_request_mib: int, memory_limit_mib: int,
) -> dict[str, Any]:
    if nodes_per_replica < MIN_NODES_PER_REPLICA:
        raise ValueError(t("llmd.nodes_per_replica_min", min=MIN_NODES_PER_REPLICA))
    lws_name = f"{name}-multi"
    cl = {"app.kubernetes.io/name": lws_name, "app.kubernetes.io/instance": name}
    res_kw = dict(
        cpu_request_millicores=cpu_request_millicores,
        cpu_limit_millicores=cpu_limit_millicores,
        memory_request_mib=memory_request_mib,
        memory_limit_mib=memory_limit_mib,
    )
    leader_c = _sglang_container(
        launch_script=launch_script, gpu_per_pod=gpu_per_pod, efa_per_pod=efa_per_pod,
        is_leader=True, sglang_image=sglang_image, model_mount_path=model_mount_path, **res_kw,
    )
    worker_c = _sglang_container(
        launch_script=launch_script, gpu_per_pod=gpu_per_pod, efa_per_pod=efa_per_pod,
        is_leader=False, sglang_image=sglang_image, model_mount_path=model_mount_path, **res_kw,
    )
    return {
        "apiVersion": "leaderworkerset.x-k8s.io/v1",
        "kind": "LeaderWorkerSet",
        "metadata": {
            "name": lws_name, "namespace": namespace,
            "labels": {**labels, "app.kubernetes.io/instance": name,
                       "kueue.x-k8s.io/queue-name": queue_name,
                       "kueue.x-k8s.io/priority-class": default_priority_class("llmd")},  # 顶层打; pod 层不打(VAP豁免)
        },
        "spec": {
            "replicas": replicas,
            "startupPolicy": "LeaderCreated",
            "leaderWorkerTemplate": {
                "size": nodes_per_replica,
                "restartPolicy": "RecreateGroupOnPodRestart",
                "leaderTemplate": {
                    "metadata": {"labels": {**cl, "role": "leader", "llmd.sgl/pool": name}},
                    "spec": _pod_spec(name=name, gpu_instance_type=gpu_instance_type,
                                      model_pvc=model_pvc, otel_image=otel_image,
                                      sglang_c=leader_c, otel_subpath="worker.yaml"),
                },
                "workerTemplate": {
                    "metadata": {"labels": {**cl, "role": "worker"}},
                    "spec": _pod_spec(name=name, gpu_instance_type=gpu_instance_type,
                                      model_pvc=model_pvc, otel_image=otel_image,
                                      sglang_c=worker_c, otel_subpath="worker.yaml"),
                },
            },
        },
    }


def render_llmd_resources(
    *,
    name: str,
    namespace: str,
    llmd_id: str,
    workspace_id: str,
    creator_id: str,
    launch_script: str,
    model_pvc: str,
    # 模型盘容器挂载点: FSx=授权 mount_path (跟开发机一致), S3=/model (兜底)
    model_mount_path: str = _MODEL_MOUNT,
    gpu_instance_type: str,
    gateway_instance_type: str,
    otel_endpoint: str,
    otel_image: str,
    replicas: int = 1,
    nodes_per_replica: int = 2,
    gpu_per_pod: int = 1,
    efa_per_pod: int = 0,
    cpu_request_millicores: int = 4000,
    cpu_limit_millicores: int = 4000,
    memory_request_mib: int = 16384,
    memory_limit_mib: int = 16384,
    gateway_image: str = _DEFAULT_GATEWAY_IMAGE,
    sglang_image: str = _DEFAULT_SGLANG_IMAGE,
    gateway_replicas: int = 1,
    gateway_extra_args: list[str] | None = None,
    gateway_cpu_request_millicores: int = 1000,
    gateway_cpu_limit_millicores: int = 4000,
    gateway_memory_request_mib: int = 2048,
    gateway_memory_limit_mib: int = 8192,
    expose_alb: bool = False,
) -> list[dict[str, Any]]:
    """渲一整组 llm-d 资源: OTel CM + gateway(RBAC+Deploy+Svc) + LWS [+ Ingress]。

    expose_alb=True 多渲一个 HTTP:80 的 internal ALB Ingress。
    """
    queue_name = f"{namespace}-localqueue"
    labels = _platform_labels(llmd_id, workspace_id, creator_id)
    resources: list[dict[str, Any]] = [_otel_configmap(name, namespace, otel_endpoint)]
    resources.extend(_gateway_rbac(name, namespace))
    resources.append(_gateway_deployment(
        name=name, namespace=namespace, queue_name=queue_name, gateway_image=gateway_image,
        otel_image=otel_image, gateway_instance_type=gateway_instance_type,
        labels=labels,
        gateway_replicas=gateway_replicas, gateway_extra_args=gateway_extra_args,
        gateway_cpu_request_millicores=gateway_cpu_request_millicores,
        gateway_cpu_limit_millicores=gateway_cpu_limit_millicores,
        gateway_memory_request_mib=gateway_memory_request_mib,
        gateway_memory_limit_mib=gateway_memory_limit_mib,
    ))
    resources.append(_gateway_service(name, namespace))
    if expose_alb:
        resources.append(_gateway_ingress(name, namespace, labels=labels))
    resources.append(_leaderworkerset(
        name=name, namespace=namespace, queue_name=queue_name, labels=labels,
        otel_image=otel_image, replicas=replicas, nodes_per_replica=nodes_per_replica,
        launch_script=launch_script, gpu_per_pod=gpu_per_pod, efa_per_pod=efa_per_pod,
        gpu_instance_type=gpu_instance_type, model_pvc=model_pvc,
        model_mount_path=model_mount_path,
        sglang_image=sglang_image,
        cpu_request_millicores=cpu_request_millicores,
        cpu_limit_millicores=cpu_limit_millicores,
        memory_request_mib=memory_request_mib,
        memory_limit_mib=memory_limit_mib,
    ))
    return resources
