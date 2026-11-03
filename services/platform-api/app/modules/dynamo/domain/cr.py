"""DynamoGraphDeployment CR 渲染器 · 纯函数, 对齐真集群实测的 dynamo-probe yaml.

Sources (authoritative):
    - 2026-07-11 demo 真集群跑通的 DynamoGraphDeployment (单机 + 多机 tp2, invoke 验过)
    - kubectl explain dynamographdeployments.spec (2026-07-09 装后 schema 全集)

Key invariants (实测坐实):
    - apiVersion: nvidia.com/v1beta1
    - kind: DynamoGraphDeployment
    - spec.backendFramework: sglang (最小切片仅 sglang; enum 还有 vllm/trtllm)
    - components: Frontend(type=frontend) + worker(type=worker)
    - 多机: worker.multinode.nodeCount + 启动脚本内 --tp-size/--ep-size
    - v1beta1 用 podTemplate (非 v1alpha1 平铺)
    - grove 给每 pod 打 kueue.x-k8s.io/managed → 走 Kueue pod integration (配额统一)

对齐推理: 模型走授权 FSx PVC (后端反查, 照训练) + 启动脚本写 --model-path; tp/ep 亦在脚本。

平台 label 契约 (★ 与 Go platform-controller 一字不差 Go 规范):
    - platform.hyperpod.io/dynamo-id      → Go resolveids.go labelDynamoID
    - platform.hyperpod.io/workspace-id   → Go labelWorkspaceID
    grove 另给 pod 打 nvidia.com/dynamo-graph-deployment-name=<CR名> (UI 定位 pod 锚点)。
"""

from __future__ import annotations

from typing import Any

from app.core.labels import sanitize_label_value
from app.core.priority_defaults import default_priority_class

DYNAMO_API_VERSION = "nvidia.com/v1beta1"
DYNAMO_KIND = "DynamoGraphDeployment"

_DEFAULT_DYNAMO_IMAGE = "nvcr.io/nvidia/ai-dynamo/sglang-runtime:1.2.1-efa-amd64"

_PLATFORM_LABEL_PREFIX = "platform.hyperpod.io"

# 模型盘挂载点兜底 (授权反查拿不到 mount_path 时用; 正常传 mount_path)
_FALLBACK_MOUNT_PATH = "/fsx"

# 机间通信 env (多机 tp/ep 走 EFA; 实测 dynamo-probe 用值)
_COMM_ENV = [
    {"name": "GLOO_SOCKET_IFNAME", "value": "eth0"},
    {"name": "NCCL_SOCKET_IFNAME", "value": "eth0"},
    {"name": "FI_PROVIDER", "value": "efa"},
]


# OTel sidecar (照 IEC otel-collector, 监控): scrape 本 pod 的 dynamo_* → 推中央
# collector → AMP。dynamo-operator/grove 不自动建 (IEC 靠 operator), 故平台自己加 sidecar +
# per-CR configmap。实测坐实 grove 保留 podTemplate 里加的 sidecar 容器 (2026-07-14)。
_OTEL_IMAGE = "602401143452.dkr.ecr.us-west-2.amazonaws.com/hyperpod/otel_collector:v1775584612408"
_OTEL_CENTRAL = "hyperpod-otel-collector.hyperpod-observability:4317"
_OTEL_CONFIG_VOLUME = "otel-cfg"

# dynamo 指标端口 (实测): worker :9090 (dynamo_component_*/work_handler_*), frontend :8000
_WORKER_METRICS_PORT = 9090
_FRONTEND_METRICS_PORT = 8000


def otel_configmap_name(cr_name: str) -> str:
    """per-CR OTel configmap 名 (与 CR 生命周期绑, create 建 delete 删)."""
    return f"dynamo-{cr_name}-otel"


def render_dynamo_otel_config(cr_name: str, namespace: str) -> str:
    """渲 OTel collector config.yaml: scrape 本 pod dynamo_* → static label → 推中央 collector.

    frontend + worker 共用一份 config (各自 sidecar 只有本 pod localhost 有对应端口,
    抓不到的 target 静默失败, 不影响)。static 注入 resource_name=<cr名> 供 UI 过滤。
    """
    return f"""receivers:
  prometheus/dynamo:
    config:
      scrape_configs:
        - job_name: 'dynamo-worker'
          scrape_interval: 15s
          metrics_path: /metrics
          static_configs:
            - targets: ['localhost:{_WORKER_METRICS_PORT}']
              labels:
                resource_name: '{cr_name}'
                namespace: '{namespace}'
                metric_source: 'dynamo-worker'
                resource_type: 'dynamo'
                pod_name: '${{POD_NAME}}'
                node_name: '${{NODE_NAME}}'
        - job_name: 'dynamo-frontend'
          scrape_interval: 15s
          metrics_path: /metrics
          static_configs:
            - targets: ['localhost:{_FRONTEND_METRICS_PORT}']
              labels:
                resource_name: '{cr_name}'
                namespace: '{namespace}'
                metric_source: 'dynamo-frontend'
                resource_type: 'dynamo'
                pod_name: '${{POD_NAME}}'
                node_name: '${{NODE_NAME}}'
exporters:
  otlp/grpc:
    endpoint: "{_OTEL_CENTRAL}"
    tls:
      insecure: true
    sending_queue:
      enabled: true
      num_consumers: 4
      queue_size: 500
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 30s
processors:
  batch:
    timeout: 10s
    send_batch_size: 100
service:
  telemetry:
    logs:
      level: "info"
  pipelines:
    metrics:
      receivers: [prometheus/dynamo]
      processors: [batch]
      exporters: [otlp/grpc]
"""


def _otel_sidecar() -> dict[str, Any]:
    return {
        "name": "otel-collector",
        "image": _OTEL_IMAGE,
        "args": ["--config=/etc/otel/config.yaml"],
        "env": [
            {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
            {"name": "NODE_NAME", "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}}},
        ],
        "resources": {
            "limits": {"cpu": "100m", "memory": "128Mi"},
            "requests": {"cpu": "50m", "memory": "64Mi"},
        },
        "volumeMounts": [
            {"name": _OTEL_CONFIG_VOLUME, "mountPath": "/etc/otel/config.yaml", "subPath": "config.yaml"}
        ],
    }


def _otel_config_volume(cr_name: str) -> dict[str, Any]:
    return {"name": _OTEL_CONFIG_VOLUME, "configMap": {"name": otel_configmap_name(cr_name)}}


def _fsx_volume(pvc_name: str) -> dict[str, Any]:
    return {"name": "fsx", "persistentVolumeClaim": {"claimName": pvc_name}}


def _dshm_volume() -> dict[str, Any]:
    # 多机 NCCL 共享内存 (实测需要, 否则通信建不起来)
    return {"name": "dshm", "emptyDir": {"medium": "Memory", "sizeLimit": "16Gi"}}


def render_dynamo_graph_deployment_cr(
    *,
    # 标识
    name: str,                     # CR metadata.name (= UI 定位 pod 的 graph-deployment-name)
    namespace: str,                # workspace ns
    dynamo_id: str,                # platform DDB id (★ label 契约)
    workspace_id: str,
    creator_id: str,
    # 模型盘 (授权 FSx PVC, 后端反查; model_path 已在 launch_script)
    fsx_pvc_name: str,
    # 挂载点 = 授权 FSx 的 mount_path (与开发机/推理一致, 用户 --model-path 按此填);
    # 反查拿不到则兜底 /fsx。★挂到哪, 盘内路径就相对哪 (踩坑: 硬编码 /fsx 丢盘名层→404)。
    fsx_mount_path: str = _FALLBACK_MOUNT_PATH,
    # 引擎 / 启动
    launch_script: str,            # 整段脚本, sh -c 跑 (含 dynamo.sglang --model-path --tp --ep)
    instance_type: str,
    backend_framework: str = "sglang",
    image: str = _DEFAULT_DYNAMO_IMAGE,
    # 多机
    node_count: int = 1,           # worker.multinode.nodeCount (单实例跨几机 TP/EP)
    replicas: int = 1,             # worker.replicas (几个独立实例数据并行); 总 pod = replicas × node_count
    # 资源 (来自资源模板, 锁单节点规格)
    gpu_per_worker: int = 1,
    cpu_request_millicores: int = 4000,
    cpu_limit_millicores: int = 4000,
    memory_request_mib: int = 16384,
    memory_limit_mib: int = 16384,
    efa_per_worker: int = 0,
    # FSx 权限: dynamo 镜像默认 uid=1000, FSx 目录 gid 挡非 root → root 跑通 (见踩坑池)
    run_as_root: bool = True,
    # 监控: 加 OTel sidecar scrape dynamo_* 推中央 collector (前提: 平台建了 configmap)
    metrics_enabled: bool = True,
    user_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Render a DynamoGraphDeployment CR dict."""
    labels = {
        **(user_labels or {}),
        f"{_PLATFORM_LABEL_PREFIX}/dynamo-id": dynamo_id,
        f"{_PLATFORM_LABEL_PREFIX}/workspace-id": workspace_id,
        f"{_PLATFORM_LABEL_PREFIX}/creator-id": sanitize_label_value(
            creator_id, fallback="unknown"
        ),
        f"{_PLATFORM_LABEL_PREFIX}/framework": backend_framework,
        # 集群 task-governance 强制 Deployment 带 queue-name, 否则被 admission 拒。
        "kueue.x-k8s.io/queue-name": f"{namespace}-localqueue",
        "kueue.x-k8s.io/priority-class": default_priority_class("dynamo"),
    }

    # Frontend: 统一入口, 内置 SVC :8000 OpenAI 兼容。
    # ★ frontend 也读模型路径 (要 tokenizer/config 注册 model card), 同样需 root 读 FSx;
    #   漏渲 securityContext → uid=1000 读不了 → 当 HF ID → 404 → /v1/models 空 (实测坑)。
    frontend_spec: dict[str, Any] = {
        "containers": [
            {
                "name": "main",
                "image": image,
                "env": [{"name": "NVIDIA_VISIBLE_DEVICES", "value": "void"}],
                "volumeMounts": [
                    {"name": "fsx", "mountPath": fsx_mount_path, "readOnly": True}
                ],
            }
        ],
        "volumes": [_fsx_volume(fsx_pvc_name)],
    }
    if run_as_root:
        frontend_spec["securityContext"] = {"runAsUser": 0, "runAsGroup": 0}
    if metrics_enabled:
        frontend_spec["containers"].append(_otel_sidecar())
        frontend_spec["volumes"].append(_otel_config_volume(name))
    frontend: dict[str, Any] = {
        "name": "Frontend",
        "type": "frontend",
        "replicas": 1,
        "podTemplate": {"spec": frontend_spec},
    }

    # worker: 跨机 TP/EP, nodeCount 多 pod 协同一个实例; 启动脚本 sh -c 跑
    worker_limits: dict[str, Any] = {"nvidia.com/gpu": str(gpu_per_worker)}
    if efa_per_worker > 0:
        worker_limits["vpc.amazonaws.com/efa"] = str(efa_per_worker)
    worker_resources = {
        "requests": {
            "nvidia.com/gpu": str(gpu_per_worker),
            "cpu": f"{cpu_request_millicores}m",
            "memory": f"{memory_request_mib}Mi",
        },
        "limits": {
            **worker_limits,
            "cpu": f"{cpu_limit_millicores}m",
            "memory": f"{memory_limit_mib}Mi",
        },
    }

    worker_pod_spec: dict[str, Any] = {
        "nodeSelector": {"node.kubernetes.io/instance-type": instance_type},
        "containers": [
            {
                "name": "main",
                "image": image,
                "command": ["/bin/sh", "-c"],
                "args": [launch_script],
                "resources": worker_resources,
                "volumeMounts": [
                    {"name": "fsx", "mountPath": fsx_mount_path, "readOnly": True},
                    {"name": "dshm", "mountPath": "/dev/shm"},
                ],
            }
        ],
        "volumes": [_fsx_volume(fsx_pvc_name), _dshm_volume()],
    }
    if run_as_root:
        worker_pod_spec["securityContext"] = {"runAsUser": 0, "runAsGroup": 0}
    if metrics_enabled:
        worker_pod_spec["containers"].append(_otel_sidecar())
        worker_pod_spec["volumes"].append(_otel_config_volume(name))

    worker: dict[str, Any] = {
        "name": "worker",
        "type": "worker",
        "replicas": replicas,
        "podTemplate": {"spec": worker_pod_spec},
    }
    # 单机 nodeCount=1 不渲 multinode (operator 按单 pod 处理); 多机才渲。
    if node_count > 1:
        worker["multinode"] = {"nodeCount": node_count}

    spec: dict[str, Any] = {
        "backendFramework": backend_framework,
        "labels": {"kueue.x-k8s.io/queue-name": f"{namespace}-localqueue"},
        "env": list(_COMM_ENV),
        "components": [frontend, worker],
    }

    return {
        "apiVersion": DYNAMO_API_VERSION,
        "kind": DYNAMO_KIND,
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": spec,
    }
