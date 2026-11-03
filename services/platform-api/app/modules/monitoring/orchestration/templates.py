"""Monitoring 模板渲染业务流.

给一个 training job 或 dev instance, 解析上下文 (namespace / pod regex /
node regex), 然后把 ``domain.promql`` 的模板全部 subst 一遍返回给前端.

职责切分:
    - 本文件不直接发 Prometheus 查询, 只负责模板字符串渲染
    - Prometheus passthrough 走 ``app.adapters.prometheus.*``
    - 节点 regex 推断要查 K8s, 属于 "IO + 业务判断", 放在这里而非 domain
"""

from __future__ import annotations

from app.modules.monitoring.api.schemas import QueryTemplate
from app.modules.monitoring.domain import promql as promql_lib
from app.modules.monitoring.domain.template_subst import (
    sort_templates,
    subst_template,
)
from app.services.k8s_client import K8sAPIError, K8sClient


async def resolve_pods_node_regex(
    k8s: K8sClient,
    namespace: str,
    *,
    job_name: str | None,
    workspace_name: str | None,
    endpoint_name: str | None = None,
    ray_cluster: str | None = None,
) -> str:
    """Return a Prometheus alternation regex matching nodes hosting this
    job/workspace/endpoint's pods (e.g. ``hyperpod-i-aaa|hyperpod-i-bbb``).

    Label keys differ by resource type:
        - HyperPodPyTorchJob pods: ``HPJob=<cr-name>`` (operator-injected)
        - DevInstance pods (Jupyter operator):
          ``workspace.jupyter.org/workspace-name=<ws-name>``
        - InferenceEndpointConfig pods: ``app=<endpoint-name>``

    Falls back to ``.*`` (all DCGM nodes) when no pods are found — better
    than empty string which would match nothing.
    """
    try:
        if job_name:
            pods = await k8s.list_pods_by_label_selector(
                namespace, f"HPJob={job_name}"
            )
        elif workspace_name:
            pods = await k8s.list_pods_by_label_selector(
                namespace,
                f"workspace.jupyter.org/workspace-name={workspace_name}",
            )
        elif endpoint_name:
            # Operator 实际打 ``app=<endpoint_name>`` (非 sagemaker.amazonaws.com/...).
            pods = await k8s.list_pods_by_label_selector(
                namespace,
                f"app={endpoint_name}",
            )
        elif ray_cluster:
            # KubeRay 给 head+worker pod 打 ``ray.io/cluster=<rayClusterName>``.
            pods = await k8s.list_pods_by_label_selector(
                namespace,
                f"ray.io/cluster={ray_cluster}",
            )
        else:
            return ".*"
    except K8sAPIError:
        return ".*"
    nodes = {(p.get("spec") or {}).get("node_name") for p in pods}
    nodes.discard(None)
    if not nodes:
        return ".*"
    return "|".join(sorted(nodes))


async def resolve_inference_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    k8s_endpoint_name: str,
) -> list[QueryTemplate]:
    """Resolve PromQL templates for an inference endpoint (SGLang).

    HyperPod Inference Operator 部署的 OTel sidecar 抓取 SGLang /metrics 时
    注入固定标签:
        namespace = <k8s ns>
        resource_name = <endpoint name, 即 CR metadata.name>
        resource_type = "inference-endpoint"
        task_type = "inference"

    所以 SGLang 系列指标用 ``resource_name="$endpoint_name"`` 过滤,
    cAdvisor / DCGM 走 ``pod=~"$pod_regex"`` (GPU 指标全切 pod 过滤,
    inference 36 模板 0 个用 node_regex, 故跳过 K8s list pods 省一次往返).
    """
    vars = {
        "namespace": k8s_namespace,
        # cAdvisor 用: InferenceEndpointConfig 起的 Deployment 名 = endpoint_name,
        # Pod 名 <ep>-<rs>-<rand>.
        "pod_regex": f"{k8s_endpoint_name}-.*",
        # SGLang OTel sidecar 注入的固定 resource_name = endpoint_name.
        "endpoint_name": k8s_endpoint_name,
    }
    return sort_templates(
        [subst_template(t, **vars) for t in promql_lib.INFERENCE_TEMPLATES]
    )


# Dynamo GPU/资源指标: 复用 INFERENCE_TEMPLATES 里节点级指标 (DCGM/cAdvisor),
# 跳过 sglang 引擎 + inference 网关类 (那些靠 IEC OTel sidecar 注入的 resource_name,
# Dynamo 没有 → "监控"; dynamo_* 引擎指标待建 OTel 抓取管道后单独接)。
_DYNAMO_MONITOR_CATEGORIES = {
    "gpu", "cpu", "memory", "network", "disk", "efa", "status", "event", "process",
}


async def resolve_dynamo_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    k8s_cr_name: str,
) -> list[QueryTemplate]:
    """Resolve Dynamo 监控模板 (GPU / Pod 资源, 节点级 DCGM/cAdvisor).

    grove 起的 pod 名 ``<cr>-0-frontend-*`` / ``<cr>-0-worker-*``, 统一前缀 ``<cr>-``;
    DCGM/cAdvisor 带 namespace+pod label (节点级 exporter 已抓), 按 pod_regex 过滤。
    sglang 引擎/网关类跳过 (Dynamo 是 dynamo_* 指标 + 需 OTel 抓取管道, 第二批)。
    """
    node_regex = await resolve_pods_node_regex(
        k8s, k8s_namespace, job_name=None, workspace_name=None, endpoint_name=None
    )
    vars = {
        "namespace": k8s_namespace,
        "pod_regex": f"{k8s_cr_name}-.*",
        "node_regex": node_regex,
        # 引擎指标用 OTel sidecar static 注入的 resource_name (= CR 名) 过滤
        "resource_name": k8s_cr_name,
    }
    # 监控 tab: GPU/资源 (复用 INFERENCE_TEMPLATES 节点级) + 引擎 tab: dynamo_* (DYNAMO_ENGINE_TEMPLATES)
    monitor = [
        t for t in promql_lib.INFERENCE_TEMPLATES if t.category in _DYNAMO_MONITOR_CATEGORIES
    ]
    return sort_templates([
        subst_template(t, **vars)
        for t in monitor + promql_lib.DYNAMO_ENGINE_TEMPLATES
    ])


async def resolve_llmd_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    k8s_name: str,
) -> list[QueryTemplate]:
    """Resolve llm-d 多机推理监控模板 (节点级 GPU/资源 + SGLang 引擎).

    llm-d (分支B) 的 OTel sidecar (cr.py ``_otel_configmap``) 抓 SGLang
    /metrics 时静态注入 ``resource_name=<base name>`` (worker + gateway 都注入),
    等同 InferenceEndpointConfig 的 OTel 行为 → 可直接复用 INFERENCE_TEMPLATES:
        - 节点级 GPU/CPU/内存/网络 (DCGM/cAdvisor) 走 pod_regex 过滤
        - SGLang 引擎业务指标 (QPS/TTFT/KV cache) 走 resource_name 过滤

    Pod 名: worker ``<name>-multi-*``, gateway ``<name>-gateway-*``, 统一前缀
    ``<name>-`` → pod_regex 一网打尽。resource_name = base name (非 gateway svc 名)。
    比 Dynamo 强: Dynamo 无 SGLang OTel 只能出节点级, llm-d 引擎指标真能出数。
    """
    vars = {
        "namespace": k8s_namespace,
        # worker (<name>-multi-*) + gateway (<name>-gateway-*) 统一前缀
        "pod_regex": f"{k8s_name}-.*",
        # OTel sidecar 静态注入的 resource_name = base name (见 cr.py _cfg)
        "endpoint_name": k8s_name,
    }
    # 剔 category="inference": 那是 IEC 前置 nginx 的 model_*/nginx_* 指标,
    # llm-d 网关是 sgl-model-gateway (无 nginx 代理) → 这批必空, 不给前端画空图。
    usable = [t for t in promql_lib.INFERENCE_TEMPLATES if t.category != "inference"]
    return sort_templates([subst_template(t, **vars) for t in usable])


# Ray 节点级监控复用 TRAINING_TEMPLATES 通用模板 (DCGM/容器/EFA + 三维度 job/pod/gpu_card),
# 排掉 PyTorchJob 专属项 (job_name/phase/condition 标签 + training-op/fault 指标)。
# Ray pod 有相同的节点级指标, 直接复用; 引擎级 ray_* 另走 RAY_ENGINE_TEMPLATES。
_TRAIN_ONLY_MARKERS = (
    "job_name", "jobName", "HPJob", "phase=", "condition=", "reason=",
    "training_op", "auto_restart", "uptime", "fault", "_restart_",
)


def _generic_node_templates() -> list[QueryTemplate]:
    """TRAINING_TEMPLATES 里仅用 namespace/pod/node 过滤的通用节点级模板 (Ray 可复用)。"""
    return [
        t
        for t in promql_lib.TRAINING_TEMPLATES
        if not any(m in t.promql for m in _TRAIN_ONLY_MARKERS)
    ]


async def resolve_rayjob_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    ray_cluster_name: str,
) -> list[QueryTemplate]:
    """Resolve RayJob 监控模板 (节点级复用训练三维模板 + Ray 引擎 ray_*).

    用 RayCluster 名 (status.rayClusterName, 非 CR 名): pod label ray.io/cluster、
    AMP label ray_io_cluster 都用它, 未 sync 时为空则返 []。
    """
    if not ray_cluster_name:
        return []
    node_regex = await resolve_pods_node_regex(
        k8s, k8s_namespace, job_name=None, workspace_name=None,
        ray_cluster=ray_cluster_name,
    )
    vars = {
        "namespace": k8s_namespace,
        "pod_regex": f"{ray_cluster_name}-.*",
        "node_regex": node_regex,
        # Ray 引擎指标 (RAY_ENGINE_TEMPLATES) 用 ray_io_cluster="$ray_cluster" 过滤
        "ray_cluster": ray_cluster_name,
    }
    return sort_templates([
        subst_template(t, **vars)
        for t in _generic_node_templates() + promql_lib.RAY_ENGINE_TEMPLATES
    ])


async def resolve_training_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    k8s_job_name: str,
) -> list[QueryTemplate]:
    """Resolve PromQL templates for a training job."""
    node_regex = await resolve_pods_node_regex(
        k8s, k8s_namespace, job_name=k8s_job_name, workspace_name=None
    )
    vars = {
        "namespace": k8s_namespace,
        "job_name": k8s_job_name,
        # K8s Job's Pod names follow `<job-name>-<random>`.
        "pod_regex": f"{k8s_job_name}-.*",
        "node_regex": node_regex,
    }
    return sort_templates(
        [subst_template(t, **vars) for t in promql_lib.TRAINING_TEMPLATES]
    )


async def resolve_dev_instance_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    k8s_workspace_name: str,
) -> list[QueryTemplate]:
    """Resolve PromQL templates for a dev instance (full panel)."""
    node_regex = await resolve_pods_node_regex(
        k8s,
        k8s_namespace,
        job_name=None,
        workspace_name=k8s_workspace_name,
    )
    vars = {
        "namespace": k8s_namespace,
        "pod_regex": f"workspace-{k8s_workspace_name}-.*",
        "node_regex": node_regex,
    }
    return [
        subst_template(t, **vars) for t in promql_lib.DEV_INSTANCE_TEMPLATES
    ]


async def resolve_dev_instance_kpi_templates(
    k8s: K8sClient,
    *,
    k8s_namespace: str,
    k8s_workspace_name: str,
) -> list[QueryTemplate]:
    """Resolve KPI-card templates for a dev instance detail page."""
    node_regex = await resolve_pods_node_regex(
        k8s,
        k8s_namespace,
        job_name=None,
        workspace_name=k8s_workspace_name,
    )
    vars = {
        "namespace": k8s_namespace,
        "pod_regex": f"workspace-{k8s_workspace_name}-.*",
        "node_regex": node_regex,
    }
    return [
        subst_template(t, **vars)
        for t in promql_lib.DEV_INSTANCE_KPI_TEMPLATES
    ]
