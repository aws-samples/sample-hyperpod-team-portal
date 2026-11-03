"""RayJob CR 渲染器 (纯函数)。

必写配方 (缺一跑不通, 实测坐实):
    - queue-name 两层: metadata.labels + head/worker template.labels (VAP 拦每个 pod)
    - submissionMode HTTPMode (不建 submitter Job, 绕开其 VAP 拦点)
    - shutdownAfterJobFinishes true (Kueue 管的 RayJob webhook 强制)
    - ttlSecondsAfterFinished ≥0 (KubeRay 不接受 -1)
    - 固定 replicas (min=max), 不开 autoscaling (第二批)
"""

from __future__ import annotations

from typing import Any

from app.core.labels import sanitize_label_value
from app.core.priority_defaults import default_priority_class

RAYJOB_API_VERSION = "ray.io/v1"
RAYJOB_KIND = "RayJob"

_DEFAULT_RAY_IMAGE = "rayproject/ray:2.9.0-gpu"       # worker (GPU node)
_DEFAULT_RAY_IMAGE_CPU = "rayproject/ray:2.9.0"       # head (CPU node)
_DEFAULT_RAY_VERSION = "2.9.0"

_PLATFORM_LABEL_PREFIX = "platform.hyperpod.io"
_S3_MOUNT_GID = 1001  # mountpoint-s3-csi 固定 gid, 进 supplementalGroups

_COMM_ENV = [
    {"name": "NCCL_SOCKET_IFNAME", "value": "eth0"},
    {"name": "FI_PROVIDER", "value": "efa"},
]


def _build_volumes_and_mounts(
    s3_datasets: list[dict[str, str]] | None,
    extra_fsx_mounts: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """volumes + volumeMounts: dshm 共享内存 + FSx 授权挂载 + S3 只读 (照训练)。"""
    volumes: list[dict[str, Any]] = [
        {"name": "dshm", "emptyDir": {"medium": "Memory", "sizeLimit": "16Gi"}}
    ]
    mounts: list[dict[str, Any]] = [{"name": "dshm", "mountPath": "/dev/shm"}]

    for idx, ds in enumerate(s3_datasets or []):
        pvc_name = ds.get("pvc_name") or f"s3-{ds['bucket'][:40]}"
        vol_name = f"s3-ds-{idx}"
        volumes.append(
            {"name": vol_name, "persistentVolumeClaim": {"claimName": pvc_name}}
        )
        mounts.append(
            {"name": vol_name, "mountPath": ds["mount_path"], "readOnly": True}
        )

    for idx, m in enumerate(extra_fsx_mounts or []):
        vol_name = f"fsx-{idx}"
        volumes.append(
            {"name": vol_name, "persistentVolumeClaim": {"claimName": m["pvc_name"]}}
        )
        mounts.append(
            {
                "name": vol_name,
                "mountPath": m["mount_path"],
                "readOnly": bool(m.get("read_only", False)),
            }
        )
    return volumes, mounts


def _render_env_secrets(
    env_secrets: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """env_secrets → valueFrom.secretKeyRef (值不进 CR 明文)。"""
    out: list[dict[str, Any]] = []
    for s in env_secrets or []:
        out.append({
            "name": s["name"],
            "valueFrom": {
                "secretKeyRef": {"name": s["secret_ref"], "key": s["secret_key"]}
            },
        })
    return out


def _group_resources(
    *,
    gpu_per_node: int,
    cpu_request_millicores: int,
    cpu_limit_millicores: int,
    memory_request_mib: int,
    memory_limit_mib: int,
    efa_per_node: int,
) -> dict[str, Any]:
    limits: dict[str, Any] = {"nvidia.com/gpu": str(gpu_per_node)}
    if efa_per_node > 0:
        limits["vpc.amazonaws.com/efa"] = str(efa_per_node)
    return {
        "requests": {
            "nvidia.com/gpu": str(gpu_per_node),
            "cpu": f"{cpu_request_millicores}m",
            "memory": f"{memory_request_mib}Mi",
        },
        "limits": {
            **limits,
            "cpu": f"{cpu_limit_millicores}m",
            "memory": f"{memory_limit_mib}Mi",
        },
    }


def _group_pod_spec(
    *,
    image: str,
    instance_type: str,
    queue_name: str,
    resources: dict[str, Any],
    container_name: str,
    env: dict[str, str] | None,
    env_secrets: list[dict[str, Any]] | None,
    volumes: list[dict[str, Any]],
    mounts: list[dict[str, Any]],
    supplemental_gids: list[int],
    run_as_root: bool,
) -> dict[str, Any]:
    """head/worker pod template。metadata.labels 打 queue-name (VAP 第二层)。"""
    user_env = [{"name": k, "value": v} for k, v in (env or {}).items()]
    container: dict[str, Any] = {
        "name": container_name,
        "image": image,
        "resources": resources,
        "env": list(_COMM_ENV) + user_env + _render_env_secrets(env_secrets),
        "volumeMounts": mounts,
    }
    pod_spec: dict[str, Any] = {
        "nodeSelector": {"node.kubernetes.io/instance-type": instance_type},
        "containers": [container],
        "volumes": volumes,
    }
    if run_as_root:
        # root 读 FSx (盘 gid 挡非 root, 同 dynamo)
        sc: dict[str, Any] = {"runAsUser": 0, "runAsGroup": 0}
        if supplemental_gids:
            sc["supplementalGroups"] = supplemental_gids
        pod_spec["securityContext"] = sc
    return {
        "metadata": {"labels": {"kueue.x-k8s.io/queue-name": queue_name}},
        "spec": pod_spec,
    }


# head sidecar 导出 driver 日志: 训练脚本真输出被 Ray 写进 head 的 job-driver 文件、
# 不进容器 stdout, CloudWatch 采不到 → sidecar tail 到自己 stdout, 走 fluent-bit 进 CW。
_DRIVER_LOG_VOLUME = "ray-driver-logs"
_DRIVER_LOG_DIR = "/tmp/ray"
# 先等文件出现再 tail: session 路径带随机、文件到作业提交才生成, tail -F 抓不到启动时
# 不存在的 glob。RayJob 一集群一次提交 → 只一个 job-driver 文件。
_DRIVER_LOG_TAIL_CMD = (
    "until ls /tmp/ray/session_latest/logs/job-driver-*.log >/dev/null 2>&1; "
    "do sleep 2; done; "
    "exec tail -n +1 -F /tmp/ray/session_latest/logs/job-driver-*.log"
)


def _inject_driver_log_sidecar(head_template: dict[str, Any], image: str) -> None:
    """head pod 原地加 driver-log sidecar + 共享 /tmp/ray emptyDir。

    volumes/mounts 是 head+worker 共享的同一 list, 必须 copy 后重新赋值, 直接 append
    会污染 worker。常规 sidecar (非原生), 拆 pod 时末尾几行可能没 flush。
    """
    spec = head_template["spec"]
    spec["volumes"] = list(spec.get("volumes") or []) + [
        {"name": _DRIVER_LOG_VOLUME, "emptyDir": {}}
    ]
    head_c = spec["containers"][0]  # ray-head
    head_c["volumeMounts"] = list(head_c.get("volumeMounts") or []) + [
        {"name": _DRIVER_LOG_VOLUME, "mountPath": _DRIVER_LOG_DIR}
    ]
    spec["containers"].append(
        {
            "name": "driver-log-tailer",
            "image": image,  # 复用 head 镜像 (必在, 有 GNU tail), 免额外拉镜像
            "command": ["/bin/sh", "-c", _DRIVER_LOG_TAIL_CMD],
            "resources": {
                "requests": {"cpu": "50m", "memory": "64Mi"},
                "limits": {"cpu": "200m", "memory": "128Mi"},
            },
            "volumeMounts": [
                {
                    "name": _DRIVER_LOG_VOLUME,
                    "mountPath": _DRIVER_LOG_DIR,
                    "readOnly": True,
                }
            ],
        }
    )


def render_rayjob_cr(
    *,
    name: str,
    namespace: str,
    rayjob_id: str,
    workspace_id: str,
    creator_id: str,
    extra_fsx_mounts: list[dict[str, Any]] | None = None,
    s3_datasets: list[dict[str, str]] | None = None,
    fsx_supplemental_gids: list[int] | None = None,
    entry_script_path: str,       # entrypoint 原样透传, 别加 bash 前缀 (否则双前缀 exit 126)
    # head 落 CPU node 用 CPU 镜像; gpu 镜像在无驱动 CPU node NVML 崩 → CrashLoop
    head_image: str = _DEFAULT_RAY_IMAGE_CPU,
    worker_image: str = _DEFAULT_RAY_IMAGE,
    worker_replicas: int = 1,
    head_instance_type: str = "",
    head_gpu: int = 0,
    head_cpu_request_millicores: int = 2000,
    head_cpu_limit_millicores: int = 4000,
    head_memory_request_mib: int = 8192,
    head_memory_limit_mib: int = 16384,
    head_efa: int = 0,
    worker_instance_type: str = "",
    gpu_per_node: int = 1,
    cpu_request_millicores: int = 2000,
    cpu_limit_millicores: int = 4000,
    memory_request_mib: int = 8192,
    memory_limit_mib: int = 16384,
    efa_per_node: int = 0,
    max_run_hours: int = 24,
    ttl_seconds_after_finished: int = 3600,   # KubeRay 要 ≥0, 不接受 -1
    backoff_limit: int = 0,
    env: dict[str, str] | None = None,
    env_secrets: list[dict[str, Any]] | None = None,
    run_as_root: bool = True,
    user_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Render a RayJob CR dict."""
    queue_name = f"{namespace}-localqueue"
    labels = {
        **(user_labels or {}),
        f"{_PLATFORM_LABEL_PREFIX}/rayjob-id": rayjob_id,
        f"{_PLATFORM_LABEL_PREFIX}/workspace-id": workspace_id,
        f"{_PLATFORM_LABEL_PREFIX}/creator-id": sanitize_label_value(
            creator_id, fallback="unknown"
        ),
        # queue-name 第一层: 顶层 CR 过 VAP
        "kueue.x-k8s.io/queue-name": queue_name,
        "kueue.x-k8s.io/priority-class": default_priority_class("rayjob"),
    }

    head_resources = _group_resources(
        gpu_per_node=head_gpu,
        cpu_request_millicores=head_cpu_request_millicores,
        cpu_limit_millicores=head_cpu_limit_millicores,
        memory_request_mib=head_memory_request_mib,
        memory_limit_mib=head_memory_limit_mib,
        efa_per_node=head_efa,
    )
    worker_resources = _group_resources(
        gpu_per_node=gpu_per_node,
        cpu_request_millicores=cpu_request_millicores,
        cpu_limit_millicores=cpu_limit_millicores,
        memory_request_mib=memory_request_mib,
        memory_limit_mib=memory_limit_mib,
        efa_per_node=efa_per_node,
    )
    volumes, mounts = _build_volumes_and_mounts(s3_datasets, extra_fsx_mounts)
    # supplementalGroups = 各 FSx gid + S3 1001 (root pod 读写授权盘)
    gids = list(fsx_supplemental_gids or [])
    if not gids:
        gids = [int(m["gid"]) for m in (extra_fsx_mounts or []) if m.get("gid") is not None]
    if s3_datasets:
        gids.append(_S3_MOUNT_GID)
    supp_gids = sorted(set(gids))

    def _tmpl(container_name: str, image: str, instance_type: str, resources: dict[str, Any]) -> dict[str, Any]:
        return _group_pod_spec(
            image=image, instance_type=instance_type, queue_name=queue_name,
            resources=resources, container_name=container_name, env=env,
            env_secrets=env_secrets, volumes=volumes, mounts=mounts,
            supplemental_gids=supp_gids, run_as_root=run_as_root,
        )

    # head 加 sidecar 把 driver 日志导到 CloudWatch
    head_template = _tmpl("ray-head", head_image, head_instance_type, head_resources)
    _inject_driver_log_sidecar(head_template, head_image)

    spec: dict[str, Any] = {
        "entrypoint": entry_script_path,
        "submissionMode": "HTTPMode",
        "shutdownAfterJobFinishes": True,
        "ttlSecondsAfterFinished": ttl_seconds_after_finished,
        "backoffLimit": backoff_limit,
        "activeDeadlineSeconds": max_run_hours * 3600,
        "rayClusterSpec": {
            "rayVersion": _DEFAULT_RAY_VERSION,
            "headGroupSpec": {
                "rayStartParams": {"dashboard-host": "0.0.0.0"},
                "template": head_template,
            },
            "workerGroupSpecs": [
                {
                    "replicas": worker_replicas,
                    "minReplicas": worker_replicas,
                    "maxReplicas": worker_replicas,
                    "groupName": "worker-group",
                    "rayStartParams": {},
                    "template": _tmpl("ray-worker", worker_image, worker_instance_type, worker_resources),
                }
            ],
        },
    }

    return {
        "apiVersion": RAYJOB_API_VERSION,
        "kind": RAYJOB_KIND,
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": spec,
    }
