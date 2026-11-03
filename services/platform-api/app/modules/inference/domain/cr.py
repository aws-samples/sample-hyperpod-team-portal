"""InferenceEndpointConfig CR 渲染器 · 纯函数, 严格对齐官方样例.

Sources (authoritative):
    - https://docs.aws.amazon.com/sagemaker/latest/dg/inference-operator.html

Key invariants:
    - apiVersion: inference.sagemaker.aws.amazon.com/v1
    - kind: InferenceEndpointConfig
    - spec.modelSourceConfig 三选一: fsx / s3 / huggingface
    - spec.worker.image: SGLang 官方 image (lmsysorg/sglang:latest)
    - spec.worker.modelInvocationPort.containerPort: 必 = SGLang --port (默 8000)
    - spec.metrics.modelMetrics.port: 必 = container_port (SGLang /metrics 同口)

Smart Routing (operator v3.x):
    - spec.routingStrategy: roundrobin / prefixaware / kvaware / session

L2 KV Cache (operator v3.x):
    - spec.kvCache.l2.enabled / backend / endpoint
"""

from __future__ import annotations

from typing import Any

from app.core.labels import sanitize_label_value
from app.core.priority_defaults import default_priority_class

# 官方 apiVersion + kind
IEC_API_VERSION = "inference.sagemaker.aws.amazon.com/v1"
IEC_KIND = "InferenceEndpointConfig"

# 默认 SGLang image
_DEFAULT_SGLANG_IMAGE = "lmsysorg/sglang:latest"

# 平台业务追溯 label · ws_id / creator / inference_id
_PLATFORM_LABEL_PREFIX = "platform.hyperpod.io"


def _model_source_config(
    *,
    source_type: str,
    fsx: dict[str, Any] | None,
    s3: dict[str, Any] | None,
    hf: dict[str, Any] | None,
) -> dict[str, Any]:
    """渲 spec.modelSourceConfig (三选一)."""
    if source_type == "fsx":
        if not fsx:
            raise ValueError("fsx model source requires fsx config")
        cfg: dict[str, Any] = {
            "modelSourceType": "fsx",
            "fsxStorage": {"fileSystemId": fsx["filesystem_id"]},
        }
        # modelLocation 空 → 不渲该字段 (operator 挂整个 mountName 层, 实测;
        # 渲空串 vs 缺字段 operator 行为可能不同, 取实测过的"缺字段")。模型路径走启动脚本。
        if fsx.get("model_location"):
            cfg["modelLocation"] = fsx["model_location"]
        if fsx.get("mount_name"):
            cfg["fsxStorage"]["mountName"] = fsx["mount_name"]
        if fsx.get("dns_name"):
            cfg["fsxStorage"]["dnsName"] = fsx["dns_name"]
        return cfg
    if source_type == "s3":
        if not s3:
            raise ValueError("s3 model source requires s3 config")
        return {
            "modelSourceType": "s3",
            "prefetchEnabled": bool(s3.get("prefetch_enabled", True)),
            "s3Storage": {
                "bucketName": s3["bucket_name"],
                "region": s3.get("region", "us-west-2"),
            },
            "modelLocation": s3["model_location"],
        }
    if source_type == "huggingface":
        if not hf:
            raise ValueError("huggingface model source requires hf config")
        return {
            "modelSourceType": "huggingface",
            "prefetchEnabled": bool(hf.get("prefetch_enabled", True)),
            "huggingFaceModel": {"modelId": hf["model_id"]},
        }
    raise ValueError(f"unknown source_type: {source_type}")


def _sglang_args(
    *,
    container_port: int,
    extra_args: list[str],
    model_mount_path: str = "/opt/ml/model",
) -> list[str]:
    """渲 SGLang launch_server args (默认兜底, 仅 UI args 框为空时用)。

    context_length 走 args 框, 此处默认 8192。
    """
    base = [
        "--model-path",
        model_mount_path,
        "--host",
        "0.0.0.0",
        "--port",
        str(container_port),
        "--enable-metrics",
        "--context-length",
        "8192",
        "--trust-remote-code",
    ]
    if extra_args:
        # 用户额外参数追加 (覆盖默认时自负其责)
        base.extend(str(a) for a in extra_args)
    return base


def _resources(
    *,
    gpu_per_replica: int,
    cpu_request_millicores: int,
    cpu_limit_millicores: int,
    memory_request_mib: int,
    memory_limit_mib: int,
) -> dict[str, Any]:
    """渲 K8s container resources (request + limit)."""
    return {
        "requests": {
            "nvidia.com/gpu": str(gpu_per_replica),
            "cpu": f"{cpu_request_millicores}m",
            "memory": f"{memory_request_mib}Mi",
        },
        "limits": {
            "nvidia.com/gpu": str(gpu_per_replica),
            "cpu": f"{cpu_limit_millicores}m",
            "memory": f"{memory_limit_mib}Mi",
        },
    }


def _container_env(
    env: dict[str, str], model_mount_path: str = "/opt/ml/model"
) -> list[dict[str, str]]:
    """渲 container env (默认 HF_HOME + offline + 禁 telemetry, 用户可覆盖)."""
    defaults = {
        "HF_HOME": model_mount_path,
        "HF_HUB_OFFLINE": "1",
        "SGLANG_DISABLE_USAGE_STATS": "1",
    }
    merged: dict[str, str] = {**defaults, **(env or {})}
    return [{"name": k, "value": v} for k, v in merged.items()]


def _kv_cache_block(l2: dict[str, Any] | None) -> dict[str, Any] | None:
    """渲 spec.kvCache (L2 开启才出现, operator v3.x 字段)."""
    if not l2 or not l2.get("enabled"):
        return None
    return {
        "l2": {
            "enabled": True,
            "backend": l2.get("backend", "redis"),
            "endpoint": l2.get("redis_endpoint", "redis-master.kvcache:6379"),
            "hitRatioMetricEnabled": True,
        }
    }


def render_inference_endpoint_cr(
    *,
    # 标识
    name: str,                         # CR metadata.name (= k8s_endpoint_name)
    namespace: str,                    # workspace ns (e.g. hyperpod-ns-demo)
    inference_id: str,                 # platform DDB id
    workspace_id: str,
    creator_id: str,
    # 模型
    model_name: str,
    model_source_type: str,
    model_mount_path: str = "/opt/ml/model",
    fsx: dict[str, Any] | None = None,
    s3: dict[str, Any] | None = None,
    hf: dict[str, Any] | None = None,
    # 引擎 / image
    image: str = _DEFAULT_SGLANG_IMAGE,
    container_port: int = 8000,
    sglang_extra_args: list[str] | None = None,
    # 完整 override (UI 两框); 空则回退默认拼装 (command 硬编码 / args=_sglang_args)
    sglang_command: list[str] | None = None,
    sglang_args: list[str] | None = None,
    # 单脚本启动:
    #   非空 → command=["/bin/sh","-c"], args=[launch_script] (sh -c 跑整段, exec 接管主进程)。
    #   优先级高于 sglang_command/args; 为空则回退两框 / 默认逻辑。
    launch_script: str | None = None,
    invocation_endpoint: str = "v1/chat/completions",
    # 资源
    instance_type: str,
    gpu_per_replica: int = 1,
    cpu_request_millicores: int = 4000,
    cpu_limit_millicores: int = 8000,
    memory_request_mib: int = 16384,
    memory_limit_mib: int = 32768,
    replicas: int = 1,
    # 路由 + L2
    routing_strategy: str = "roundrobin",
    l2_kv_cache: dict[str, Any] | None = None,
    # 监控 / env
    metrics_enabled: bool = True,
    env: dict[str, str] | None = None,
    # 公网 SageMaker endpoint: False 不渲 endpointName → operator 不建
    # SageMaker endpoint (省 1 SageMaker ENI/子网 + 实例计费), 仅 ClusterIP/ALB 可达。
    public_endpoint: bool = False,
    # 用户自定义 label: 已经 validate_user_labels 校验; 平台 label 后写覆盖同名。
    user_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Render an InferenceEndpointConfig CR dict (SGLang).

    Returns:
        dict 直接喂 ``CustomObjectsApi.create_namespaced_custom_object``.
    """
    labels = {
        **(user_labels or {}),
        f"{_PLATFORM_LABEL_PREFIX}/inference-id": inference_id,
        f"{_PLATFORM_LABEL_PREFIX}/workspace-id": workspace_id,
        # creator_id 可能是邮箱格式 username (含 @), 合法化成 K8s label value 否则 422
        f"{_PLATFORM_LABEL_PREFIX}/creator-id": sanitize_label_value(creator_id, fallback="unknown"),
        f"{_PLATFORM_LABEL_PREFIX}/framework": "sglang",
        # 集群侧 hyperpod-task-governance-admission-policy 强制要求所有 Deployment 带
        # 此 label, 否则被 ValidatingAdmissionPolicy 拒. 命名约定: <namespace>-localqueue.
        "kueue.x-k8s.io/queue-name": f"{namespace}-localqueue",
        # 统一默认 common-priority=80 (产品决策 2026-06-11; 三类任务同档,
        # 差异化靠优先级管理页手调单任务)。
        "kueue.x-k8s.io/priority-class": default_priority_class("inference"),
    }

    spec: dict[str, Any] = {
        "modelName": model_name,
        "instanceType": instance_type,
        "invocationEndpoint": invocation_endpoint,
        "replicas": replicas,
        "modelSourceConfig": _model_source_config(
            source_type=model_source_type, fsx=fsx, s3=s3, hf=hf
        ),
        "worker": {
            "image": image,
            # command/args 三种来源, 优先级 launch_script > 两框 > 默认拼装:
            #   1) launch_script (单脚本): command=["/bin/sh","-c"], args=[script]
            #   2) sglang_command/args 两框非空则整体覆盖
            #   3) 默认 (command 硬编码 / args 拼装)
            "command": ["/bin/sh", "-c"]
            if launch_script
            else list(sglang_command)
            if sglang_command
            else ["python3", "-m", "sglang.launch_server"],
            "args": [launch_script]
            if launch_script
            else list(sglang_args)
            if sglang_args
            else _sglang_args(
                container_port=container_port,
                extra_args=sglang_extra_args or [],
                model_mount_path=model_mount_path,
            ),
            "modelInvocationPort": {
                "containerPort": container_port,
                "name": "http",
            },
            "modelVolumeMount": {
                "name": "model-weights",
                "mountPath": model_mount_path,
            },
            "resources": _resources(
                gpu_per_replica=gpu_per_replica,
                cpu_request_millicores=cpu_request_millicores,
                cpu_limit_millicores=cpu_limit_millicores,
                memory_request_mib=memory_request_mib,
                memory_limit_mib=memory_limit_mib,
            ),
            "environmentVariables": _container_env(env or {}, model_mount_path),
        },
    }

    # 留空 endpointName → operator 不建 SageMaker endpoint
    if public_endpoint:
        spec["endpointName"] = name

    if metrics_enabled:
        spec["metrics"] = {
            "enabled": True,
            "modelMetrics": {
                "port": container_port,   # SGLang /metrics 同 http port
                "path": "/metrics",
            },
        }

    # Smart Routing — 必须嵌在 intelligentRoutingSpec 下, 且 enabled=true 才激活.
    # CRD 路径: spec.intelligentRoutingSpec.{enabled, routingStrategy}
    # (顶层 spec.routingStrategy 不存在, 写了会被 K8s structural schema reject)
    # enum: prefixaware(默认) / kvaware / session / roundrobin
    # 注: intelligentRouting 只能创建时设, 改已有 endpoint 会被 operator reject;
    #     enabled 一旦设定不可改; 单副本 (replicas=1) 路由无实际分发效果.
    if routing_strategy and routing_strategy != "roundrobin":
        spec["intelligentRoutingSpec"] = {
            "enabled": True,
            "routingStrategy": routing_strategy,
        }

    # L2 KV Cache (开启才注入)
    kv_block = _kv_cache_block(l2_kv_cache)
    if kv_block:
        spec["kvCache"] = kv_block

    return {
        "apiVersion": IEC_API_VERSION,
        "kind": IEC_KIND,
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": spec,
    }
