# app/modules/logs/domain/stream_naming.py
"""CloudWatch log stream 名解析 (纯函数).

Fluent Bit stream 名结构 (实测):
    FluentBit/kube.var.log.containers.{pod_name}_{namespace}_{container}-{container_id}.log

训练 pod 的 stream 前缀: FluentBit/kube.var.log.containers.{k8s_job_name}-pods-
只解析 container == "trainer" 的 (排除 pod-manager / code-sync)。
"""

from __future__ import annotations

_PREFIX = "FluentBit/kube.var.log.containers."


def trainer_stream_prefix(k8s_job_name: str) -> str:
    """该 task 训练 pod 的 stream 名公共前缀 (含 -pods- 锁定训练 pod)."""
    return f"{_PREFIX}{k8s_job_name}-pods-"


def parse_stream_name(stream: str) -> dict[str, str] | None:
    """解析 trainer stream 名 → {pod_name, pod_short, container, container_id}.

    非 FluentBit 容器 stream / 非 trainer 容器 → None.
    """
    if not stream.startswith(_PREFIX):
        return None
    body = stream[len(_PREFIX):]
    if body.endswith(".log"):
        body = body[: -len(".log")]
    # body = {pod_name}_{namespace}_{container}-{container_id}
    parts = body.split("_")
    if len(parts) < 3:
        return None
    pod_name = parts[0]
    container_seg = parts[-1]  # {container}-{container_id}
    # container 与 container_id 用最后一个 '-' 分隔
    dash = container_seg.rfind("-")
    if dash <= 0:
        return None
    container = container_seg[:dash]
    container_id = container_seg[dash + 1:]
    if not container_id:
        return None
    if container != "trainer":
        return None
    pod_short = pod_name.rsplit("-", 1)[-1]
    return {
        "pod_name": pod_name,
        "pod_short": pod_short,
        "container": container,
        "container_id": container_id,
    }


def inference_stream_prefix(k8s_endpoint_name: str) -> str:
    """推理 pod 的 stream 名公共前缀 (= endpoint CR name, pod 名以此开头)。

    推理 pod 名 = {k8s_endpoint_name}-{rs_hash}-{pod_hash} (实测 aaa-37ca18-797f795b4-z2shk)。
    """
    return f"{_PREFIX}{k8s_endpoint_name}-"


def parse_inference_stream_name(
    stream: str, k8s_endpoint_name: str
) -> dict[str, str] | None:
    """解析推理 stream 名 → {pod_name, pod_short, container, container_id}。

    只保留主容器 (container == k8s_endpoint_name), 排除 otel-collector / sidecar-reverse-proxy。
    实测: FluentBit/kube.var.log.containers.{pod}_{ns}_{container}-{cid}.log
    """
    if not stream.startswith(_PREFIX):
        return None
    body = stream[len(_PREFIX):]
    if body.endswith(".log"):
        body = body[: -len(".log")]
    parts = body.split("_")
    if len(parts) < 3:
        return None
    pod_name = parts[0]
    container_seg = parts[-1]  # {container}-{container_id}
    dash = container_seg.rfind("-")
    if dash <= 0:
        return None
    container = container_seg[:dash]
    container_id = container_seg[dash + 1:]
    if not container_id:
        return None
    # 只要主容器 (= endpoint name); otel-collector / sidecar-reverse-proxy 跳过
    if container != k8s_endpoint_name:
        return None
    pod_short = pod_name.rsplit("-", 1)[-1]
    return {
        "pod_name": pod_name,
        "pod_short": pod_short,
        "container": container,
        "container_id": container_id,
    }


def dynamo_stream_prefix(k8s_cr_name: str) -> str:
    """Dynamo (多机推理) pod 的 stream 名公共前缀 (= DGD CR 名, pod 名以此开头)。

    grove 给每个 frontend/worker pod 打名 {cr_name}-{replica}-{...}-{hash}
    (实测 2026-07-15: test-multi-01-...-0-frontend-wckkj /
    ...-0-worker-0-worker-ldr-g8dw4 / ...-0-worker-0-worker-wkr-zkk5z)。
    frontend 与 worker pod 名 pattern 不同, 但都以 {cr_name}- 开头, 前缀圈定对两者都成立。
    """
    return f"{_PREFIX}{k8s_cr_name}-"


def parse_dynamo_stream_name(stream: str) -> dict[str, str] | None:
    """解析 Dynamo stream 名 → {pod_name, pod_short, container, container_id}。

    只保留主容器 (container == "main"), 排除 otel-collector sidecar。
    实测 (2026-07-15): FluentBit/kube.var.log.containers.{pod}_{ns}_main-{cid}.log
    frontend 与 worker pod 的主容器名都是 "main" (与推理不同: 推理主容器名 = endpoint name)。
    """
    if not stream.startswith(_PREFIX):
        return None
    body = stream[len(_PREFIX):]
    if body.endswith(".log"):
        body = body[: -len(".log")]
    # body = {pod_name}_{namespace}_{container}-{container_id}
    parts = body.split("_")
    if len(parts) < 3:
        return None
    pod_name = parts[0]
    container_seg = parts[-1]  # {container}-{container_id}
    dash = container_seg.rfind("-")
    if dash <= 0:
        return None
    container = container_seg[:dash]
    container_id = container_seg[dash + 1:]
    if not container_id:
        return None
    # 只要主容器 "main"; otel-collector 跳过
    if container != "main":
        return None
    pod_short = pod_name.rsplit("-", 1)[-1]
    return {
        "pod_name": pod_name,
        "pod_short": pod_short,
        "container": container,
        "container_id": container_id,
    }


# llm-d 两类主容器名: LWS 的 sglang + gateway Deployment 的 gateway。
# 允许列表过滤, 排除 sglang pod 上的 worker-otel-collector sidecar 及 kube-api-access。
_LLMD_MAIN_CONTAINERS = frozenset({"sglang", "gateway"})


def llmd_stream_prefix(k8s_name: str) -> str:
    """llm-d pod 的 stream 名公共前缀 (= CR base 名, LWS 与 gateway pod 都以此开头)。

    实测 2026-07-30: LWS pod {k8s_name}-multi-0 / {k8s_name}-multi-0-1,
    gateway pod {k8s_name}-gateway-<rs_hash>-<pod_hash>。两类都以 {k8s_name}- 开头,
    前缀圈定对两者都成立 (含"只有 gateway"的任务)。
    """
    return f"{_PREFIX}{k8s_name}-"


def parse_llmd_stream_name(stream: str) -> dict[str, str] | None:
    """解析 llm-d stream 名 → {pod_name, pod_short, container, container_id}。

    只保留主容器 (container in {"sglang", "gateway"}), 排除 worker-otel-collector
    sidecar / kube-api-access。实测 2026-07-30: sglang pod 带 otel sidecar, gateway
    pod 无 sidecar。stream 名结构同其他类型: {pod}_{ns}_{container}-{cid}.log。
    """
    if not stream.startswith(_PREFIX):
        return None
    body = stream[len(_PREFIX):]
    if body.endswith(".log"):
        body = body[: -len(".log")]
    parts = body.split("_")
    if len(parts) < 3:
        return None
    pod_name = parts[0]
    container_seg = parts[-1]  # {container}-{container_id}
    dash = container_seg.rfind("-")
    if dash <= 0:
        return None
    container = container_seg[:dash]
    container_id = container_seg[dash + 1:]
    if not container_id:
        return None
    if container not in _LLMD_MAIN_CONTAINERS:
        return None
    pod_short = pod_name.rsplit("-", 1)[-1]
    return {
        "pod_name": pod_name,
        "pod_short": pod_short,
        "container": container,
        "container_id": container_id,
    }


# Ray 主容器名: head pod 的 ray-head + worker pod 的 ray-worker。
# worker pod 另有 wait-gcs-ready init 容器 (额外产流)，展示时过滤掉，只留这两个主容器。
_RAY_MAIN_CONTAINERS = {"ray-head", "ray-worker"}

# head pod 上的 driver 日志 sidecar 容器: tail /tmp/ray/session_latest/logs/job-driver-*.log
# (用户 entrypoint 真实训练输出) 转写到 stdout，由 Fluent Bit 打到 CloudWatch。
# 与系统容器 (ray-head) 分属两条 stream，一并放行展示。
_RAY_DRIVER_CONTAINER = "driver-log-tailer"
_RAY_SHOWN_CONTAINERS = _RAY_MAIN_CONTAINERS | {_RAY_DRIVER_CONTAINER}


def ray_stream_prefix(ray_cluster_name: str) -> str:
    """Ray (rayjob) pod 的 stream 名公共前缀 (= rayClusterName，pod 名以此开头)。

    ⚠️ 锚点是 rayClusterName (= CR.status.rayClusterName，带随机后缀)，**不是 CR 名**。
    实测: head pod = {rayClusterName}-head-*，
    worker pod = {rayClusterName}-worker-group-worker-*，两者都以 {rayClusterName}- 开头。
    """
    return f"{_PREFIX}{ray_cluster_name}-"


def parse_ray_stream_name(stream: str) -> dict[str, str] | None:
    """解析 Ray stream 名 → {pod_name, pod_short, container, container_id}。

    保留主容器 (ray-head / ray-worker) 与 head 上的 driver 日志 sidecar
    (driver-log-tailer)，排除 worker 的 wait-gcs-ready init 容器。
    格式: FluentBit/kube.var.log.containers.{pod}_{ns}_{container}-{cid}.log
    """
    if not stream.startswith(_PREFIX):
        return None
    body = stream[len(_PREFIX):]
    if body.endswith(".log"):
        body = body[: -len(".log")]
    parts = body.split("_")
    if len(parts) < 3:
        return None
    pod_name = parts[0]
    container_seg = parts[-1]  # {container}-{container_id}
    dash = container_seg.rfind("-")
    if dash <= 0:
        return None
    container = container_seg[:dash]
    container_id = container_seg[dash + 1:]
    if not container_id:
        return None
    if container not in _RAY_SHOWN_CONTAINERS:  # 排 wait-gcs-ready init 容器
        return None
    pod_short = pod_name.rsplit("-", 1)[-1]
    return {
        "pod_name": pod_name,
        "pod_short": pod_short,
        "container": container,
        "container_id": container_id,
    }


# 开发机 (Workspace CR) 展示的容器: 主容器 workspace + init 容器 direct-ssh-init。
# 排除 ssm-agent-sidecar 与 workspace-init-container。
# Spaces operator 把 Workspace CR 建成名为 workspace-{CR名} 的 Deployment,
# 故 pod 名 = workspace-{k8s_workspace_name}-{rs_hash}-{pod_hash}, 前缀含 workspace- 字面量。
_DEV_SHOWN_CONTAINERS: frozenset[str] = frozenset({"workspace", "direct-ssh-init"})


def devinstance_stream_prefix(k8s_workspace_name: str) -> str:
    """开发机 pod 的 stream 名公共前缀 (= workspace-{CR名}, pod 名以此开头)。

    ⚠️ CR 名前有 workspace- 字面前缀 (operator 的 Deployment 命名), 本类型独有。
    实测: pod 名 = workspace-{k8s_workspace_name}-{rs_hash}-{pod_hash}。
    """
    return f"{_PREFIX}workspace-{k8s_workspace_name}-"


def parse_devinstance_stream_name(stream: str) -> dict[str, str] | None:
    """解析开发机 stream 名 → {pod_name, pod_short, container, container_id}。

    保留主容器 workspace 与 init 容器 direct-ssh-init;排除 ssm-agent-sidecar /
    workspace-init-container。格式: FluentBit/kube.var.log.containers.{pod}_{ns}_{container}-{cid}.log
    """
    if not stream.startswith(_PREFIX):
        return None
    body = stream[len(_PREFIX):]
    if body.endswith(".log"):
        body = body[: -len(".log")]
    parts = body.split("_")
    if len(parts) < 3:
        return None
    pod_name = parts[0]
    container_seg = parts[-1]  # {container}-{container_id}
    dash = container_seg.rfind("-")
    if dash <= 0:
        return None
    container = container_seg[:dash]
    container_id = container_seg[dash + 1:]
    if not container_id:
        return None
    if container not in _DEV_SHOWN_CONTAINERS:
        return None
    pod_short = pod_name.rsplit("-", 1)[-1]
    return {
        "pod_name": pod_name,
        "pod_short": pod_short,
        "container": container,
        "container_id": container_id,
    }


def assign_seq(streams: list[dict]) -> list[dict]:
    """给每个 stream 标 seq (同 pod_short 内按 first_ts 升序, #1 最早).

    输入/输出都是扁平 list (不聚合结构); 每个元素原地补 "seq" 字段。
    每个 stream dict 至少含: pod_short, first_ts。
    """
    by_pod: dict[str, list[dict]] = {}
    for s in streams:
        by_pod.setdefault(s["pod_short"], []).append(s)
    for group in by_pod.values():
        group.sort(key=lambda s: s["first_ts"])
        for i, s in enumerate(group, start=1):
            s["seq"] = i
    return streams
