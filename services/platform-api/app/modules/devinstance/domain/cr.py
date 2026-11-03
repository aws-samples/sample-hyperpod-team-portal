"""CR 渲染器 · 纯函数 · 严格对齐 AWS 官方样板.

三个 kind:
    - Workspace               workspace.jupyter.org/v1alpha1
    - WorkspaceTemplate       workspace.jupyter.org/v1alpha1
    - WorkspaceConnection     connection.workspace.jupyter.org/v1alpha1 (aggregated API)

官方 URL:
    https://docs.aws.amazon.com/sagemaker/latest/dg/create-manage-spaces.html
    https://docs.aws.amazon.com/sagemaker/latest/dg/customization.html
    https://docs.aws.amazon.com/sagemaker/latest/dg/vscode-access.html

铁律:
    - 输出 dict 的 key 路径必须是对应 CRD 官方样板的子集
      (CI `pytest -m cr_compliance` 守门)
    - 不能 import adapters/k8s · db · persistence · orchestration
    - 不引 pydantic schema · 只接受 primitives / dict (测试友好)
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import t

from .lifecycle_hook import SEED_COMMAND

# 常量: 跨渲染器共享
WORKSPACE_API_VERSION = "workspace.jupyter.org/v1alpha1"
WORKSPACE_KIND = "Workspace"
WORKSPACE_TEMPLATE_KIND = "WorkspaceTemplate"

CONNECTION_API_VERSION = "connection.workspace.jupyter.org/v1alpha1"
CONNECTION_KIND = "WorkspaceConnection"

# SageMaker Spaces 惯例 namespace
TEMPLATE_NS = "jupyter-k8s-system"

# 官方 primaryStorage 标准挂载路径 (customization.html 'Template' 节).
# CRD spec.storage.mountPath 默认 /home/jovyan (Jupyter 上游语义),
# 和 SMD 镜像的 sagemaker-user 不一致, 必须显式覆盖.
PRIMARY_MOUNT_PATH = "/home/sagemaker-user"

# 官方 customization.html example 的 entrypoint 路径 (按 appType 分)
ENTRYPOINT_BY_APP: dict[str, str] = {
    "jupyterlab": "/opt/amazon/sagemaker/workspace/bin/entrypoint-workspace-jupyterlab",
    "code-editor": "/opt/amazon/sagemaker/workspace/bin/entrypoint-workspace-code-editor",
}


def render_workspace_cr(
    *,
    name: str = "demo-workspace",
    # default 取集群里一定存在的 team namespace · 给 CR compliance dry-run 用
    namespace: str = "hyperpod-ns-team-a-nlp",
    display_name: str = "Demo Workspace",
    template_name: str = "sagemaker-jupyter-template",
    app_type: str = "jupyterlab",
    image: str = "public.ecr.aws/sagemaker/sagemaker-distribution:latest-gpu",
    cpu_millicores: int = 2000,
    memory_mib: int = 8192,
    gpu_count: int = 0,
    efa_count: int = 0,
    storage_size_gib: int = 5,
    env: dict[str, str] | None = None,
    volume_mounts: list[dict[str, str]] | None = None,
    labels: dict[str, str] | None = None,
    kueue_queue_name: str | None = None,
    priority_class: str | None = None,
    primary_gid: int | None = None,
    supplemental_gids: list[int] | None = None,
    service_account_name: str | None = None,
    preferred_instance_groups: list[str] | None = None,
    instance_type: str | None = None,
    instance_types: list[str] | None = None,
) -> dict[str, Any]:
    """渲染 Workspace CR.

    Args:
        volume_mounts: 每项 {"name": ..., "mount_path": ..., "pvc_name": ...}
        labels: 额外 labels (会与 kueue 标签合并). 保留前缀 workspace.jupyter.org/
            不要用 (operator 拒绝).
        kueue_queue_name: HyperPod Task Governance ValidatingAdmissionPolicy
            要求 hyperpod-ns-* 下的 Deployment 必须带 kueue.x-k8s.io/queue-name
            · 这里是 Workspace CR, 由 operator 透传到 Deployment.
        priority_class: Kueue WorkloadPriorityClass 名 (label
            kueue.x-k8s.io/priority-class). 跟训练/推理一致的机制. 引用不存在的
            class 时 Kueue 回退 priority 0 (不报错).
        primary_gid: ws 固有主 gid (runAsGroup + fsGroup). 1 ws = 1 team = 1 主 gid.
            没挂 FSx 时传 None, 不覆盖 template default.
        supplemental_gids: 该开发机所有被挂载目录的 gid 列表 (含 share 来的别 team).
            进 supplementalGroups, 让进程能读写多个组的目录.
        instance_type: 非空则 required nodeAffinity 锁该机型 (与健康过滤同 term, AND)。
        preferred_instance_groups: CPU 开发机软优先调度的 instance group 名列表
            (按机型 GPU=0 实时筛出)。渲染成 nodeAffinity preferred (weight=100,
            软优先, 满了降级不 Pending)。空 → 不加 preferred。无论传不传都加
            health required (node-health-status In [Schedulable]) 过滤不可调度节点。
    """
    # ------ metadata ------
    meta_labels: dict[str, str] = dict(labels or {})
    if kueue_queue_name:
        meta_labels["kueue.x-k8s.io/queue-name"] = kueue_queue_name
    if priority_class:
        meta_labels["kueue.x-k8s.io/priority-class"] = priority_class

    metadata: dict[str, Any] = {
        "name": name,
        "namespace": namespace,
    }
    if meta_labels:
        metadata["labels"] = meta_labels

    # ------ resources ------
    resources = build_resources(
        cpu_millicores=cpu_millicores,
        memory_mib=memory_mib,
        gpu_count=gpu_count,
        efa_count=efa_count,
    )

    # ------ spec ------
    spec: dict[str, Any] = {
        "displayName": display_name,
        "templateRef": {
            "name": template_name,
            "namespace": TEMPLATE_NS,
        },
        # Public: 非 owner (管理员等) 也能操作/删除该开发机。OwnerOnly 会让
        # spaces admission webhook 只放行 owner 本人, 管理员都删不了。
        "ownershipType": "Public",
        "accessType": "Public",
        "appType": app_type,
        "image": image,
        "desiredStatus": "Running",
        "resources": resources,
        "storage": {
            "size": f"{storage_size_gib}Gi",
            # 官方 CRD 默认 /home/jovyan · SMD 镜像用 sagemaker-user, 必须显式覆盖
            "mountPath": PRIMARY_MOUNT_PATH,
        },
        "env": [
            {"name": k, "value": v} for k, v in (env or {}).items()
        ],
        # postStart 每次 Pod 启动都跑 (Stop→Start 重建).
        # 从 /etc/skel + 镜像 seed 拷到 EBS 空卷, 幂等.
        "lifecycle": {
            "postStart": {
                "exec": {
                    "command": SEED_COMMAND,
                },
            },
        },
    }

    # JupyterLab base_url: 平台代理走子路径 /api/v1/dev-instances/{id}/proxy/ 访问,
    # 必须让 jupyter 以该前缀为 base_url 启动 (create.py 注入 WORKSPACE_BASE_URL),
    # 否则代理带前缀转发时 jupyter 认不出路径 → 404。
    # 镜像入口 start-jupyter-server 只按 SAGEMAKER_APP_TYPE 设 base_url, 不读
    # WORKSPACE_BASE_URL; 且 spaces add-on 升级 (native SSH) 会覆盖入口链。故不改
    # 入口、不重建镜像, 改用每实例 CR 的 containerConfig.command 覆盖: 起容器时先写
    # 用户级 jupyter 配置 (base_url = WORKSPACE_BASE_URL), 再 exec 原入口
    # (native-ssh wrapper → supervisord → sshd + jupyter, SSH 不受影响)。
    # - 写 ~/.jupyter 只需 uid 1000, 不依赖 sudo → BYOI 自定义镜像也通用
    #   (/etc/jupyter 需 root, 某些镜像无免密 sudo)。
    # - postStart SEED_COMMAND 用 cp -rn (no-clobber) 且我们在 exec 前先写, 冲不掉。
    # - 用 ; 而非 && 串 exec: 万一写配置失败也不阻断 jupyter 启动 (退化回代理 404,
    #   但不 crash-loop)。
    # - code-editor 走代理 HTML/remoteAuthority rewrite, 不依赖 base_url, 故不加此段。
    if app_type == "jupyterlab":
        jl_entrypoint = ENTRYPOINT_BY_APP["jupyterlab"]
        spec["containerConfig"] = {
            "command": [
                "/bin/bash",
                "-lc",
                (
                    'mkdir -p "$HOME/.jupyter" 2>/dev/null; '
                    "printf '%s\\n' "
                    "'import os' "
                    "'_b = os.environ.get(\"WORKSPACE_BASE_URL\")' "
                    "'if _b:' "
                    "'    c.ServerApp.base_url = _b' "
                    '> "$HOME/.jupyter/jupyter_server_config.py" 2>/dev/null; '
                    f"exec {jl_entrypoint}"
                ),
            ],
        }

    # serviceAccountName: 指定 pod 用哪个 SA. 设成 workspace-default (已 Pod Identity
    # 关联 platform-pod-role) 让开发机能访问 AWS 资源; 不传则 operator 默认填 default
    # (default SA 无 role, 访问 AWS 无权限).
    if service_account_name:
        spec["serviceAccountName"] = service_account_name

    # 不写 spec.idleShutdown · 平台明确禁用空闲检测.
    # 原因: spaces operator 探测主容器 :8888 /api/idle, 但 VSCode Remote-SSH
    # 写代码 + SSM 终端跑命令都不经过该端口, 容易误停. 仅支持手动停.

    # securityContext · 仅在 ws 挂了 FSx 时才覆盖 template default (见 build_security_context)。
    spec.update(build_security_context(primary_gid, supplemental_gids))

    # volumes (P2) · spec.volumes[] (customization.html 'Additional storage').
    # CRD 硬拦 name=='workspace-storage', pydantic VolumeMount 已拦截.
    # name 字段: 前端勾选模式不传, 这里按 mount_path slug 自动生成; 老开发机
    # row 持久化的 name 透传 (vm.get('name') 命中走透传).
    # sub_path 字段: 现在不传. FSx 子目录隔离已上移到 PV 层 (mountname 拼 subdir,
    # 见 adapters/k8s/workspace_resources.create_fsx_pv), 跟 S3 用 prefix 圈定一致.
    # 原因: Spaces operator 0.0.16 的 Workspace CRD spec.volumes[] 不认 subPath,
    # 传了会被 structural prune 丢弃 (容器仍挂到 FSx 根, 隔离失效).
    # _build_volume_entry 仍兼容 sub_path (老数据/未来 operator 支持时无害).
    if volume_mounts:
        spec["volumes"] = build_volumes(volume_mounts)

    spec["affinity"] = build_affinity(
        instance_types=instance_types,
        instance_type=instance_type,
        preferred_instance_groups=preferred_instance_groups,
    )

    return {
        "apiVersion": WORKSPACE_API_VERSION,
        "kind": WORKSPACE_KIND,
        "metadata": metadata,
        "spec": spec,
    }


def build_resources(
    *,
    cpu_millicores: int,
    memory_mib: int,
    gpu_count: int = 0,
    efa_count: int = 0,
) -> dict[str, Any]:
    """spec.resources (requests==limits)。抽出供渲染与改规格 patch 共用。

    GPU / EFA 只在 >0 时下发。EFA extended resource 独立于 GPU: 请求它本身就是
    调度约束 — 只落到有 EFA 容量的节点, 池内无 EFA 机型则 Pending (同 GPU 语义)。
    """
    resources: dict[str, Any] = {
        "requests": {
            "cpu": f"{cpu_millicores}m",
            "memory": f"{memory_mib}Mi",
        },
        "limits": {
            "cpu": f"{cpu_millicores}m",
            "memory": f"{memory_mib}Mi",
        },
    }
    if gpu_count > 0:
        resources["requests"]["nvidia.com/gpu"] = str(gpu_count)
        resources["limits"]["nvidia.com/gpu"] = str(gpu_count)
    if efa_count > 0:
        resources["requests"]["vpc.amazonaws.com/efa"] = str(efa_count)
        resources["limits"]["vpc.amazonaws.com/efa"] = str(efa_count)
    return resources


def build_affinity(
    *,
    instance_types: list[str] | None = None,
    instance_type: str | None = None,
    preferred_instance_groups: list[str] | None = None,
) -> dict[str, Any]:
    """spec.affinity (只含 nodeAffinity)。抽出供渲染与改规格 patch 共用。

    required  健康过滤 — 只调度到 SageMaker 标记 Schedulable 的健康节点 (恒有);
              机型硬锁 (instance_types 列表优先, 否则回退单 instance_type; 与健康
              过滤同 term = AND, 用 node.kubernetes.io/instance-type label)。
    preferred CPU IG 软优先 — CPU 开发机优先落 CPU instance group, 满了降级到
              任意节点 (weight=100, 纯软优先, 不 Pending)。
    字段在 Workspace CRD 支持范围内 (affinity 节)。
    """
    match_exprs: list[dict[str, Any]] = [
        {
            "key": "sagemaker.amazonaws.com/node-health-status",
            "operator": "In",
            "values": ["Schedulable"],
        }
    ]
    # 机型约束: instance_types (列表, 资源池展开) 优先; 否则回退单 instance_type (兼容)。
    # 空列表/None → 不加约束 (只留健康过滤)。
    _types = instance_types if instance_types is not None else (
        [instance_type] if instance_type else []
    )
    if _types:
        match_exprs.append({
            "key": "node.kubernetes.io/instance-type",
            "operator": "In",
            "values": list(_types),
        })
    node_affinity: dict[str, Any] = {
        "requiredDuringSchedulingIgnoredDuringExecution": {
            "nodeSelectorTerms": [{"matchExpressions": match_exprs}]
        }
    }
    if preferred_instance_groups:
        node_affinity["preferredDuringSchedulingIgnoredDuringExecution"] = [
            {
                "weight": 100,
                "preference": {
                    "matchExpressions": [
                        {
                            "key": "sagemaker.amazonaws.com/instance-group-name",
                            "operator": "In",
                            "values": list(preferred_instance_groups),
                        }
                    ]
                },
            }
        ]
    return {"nodeAffinity": node_affinity}


def render_template_cr(
    *,
    name: str = "my-jupyter-template",
    display_name: str = "My Jupyter Template",
    description: str = "",
    app_type: str = "jupyterlab",
    default_image: str = "public.ecr.aws/sagemaker/sagemaker-distribution:latest-cpu",
    allowed_images: list[str] | None = None,
    default_cpu_millicores: int = 1000,
    default_memory_mib: int = 8192,
    default_storage_size_gib: int = 10,
    min_storage_size_gib: int = 5,
    max_storage_size_gib: int = 50,
    allow_secondary_storages: bool = True,
) -> dict[str, Any]:
    """渲染 WorkspaceTemplate CR (管理员 BYOI).

    按官方 customization.html example 逐字段映射, 不加自创字段.
    accessStrategy / podSecurityContext 用官方示例默认值.
    """
    if app_type not in ENTRYPOINT_BY_APP:
        raise ValueError(
            t("devinstance.app_type_invalid", allowed=list(ENTRYPOINT_BY_APP), app_type=app_type)
        )
    entrypoint = ENTRYPOINT_BY_APP[app_type]
    cpu_str = f"{default_cpu_millicores}m"
    mem_gib = max(default_memory_mib // 1024, 1)

    allowed = list(allowed_images) if allowed_images else [default_image]

    return {
        "apiVersion": WORKSPACE_API_VERSION,
        "kind": WORKSPACE_TEMPLATE_KIND,
        "metadata": {
            "name": name,
            "namespace": TEMPLATE_NS,
            "labels": {
                # 自定义前缀 OK (workspace.jupyter.org/ 是保留前缀,不能用)
                "hyperpod-ui/template-type": app_type,
            },
        },
        "spec": {
            "displayName": display_name,
            "description": description,
            "defaultImage": default_image,
            "allowedImages": allowed,
            "defaultResources": {
                "requests": {"cpu": cpu_str, "memory": f"{mem_gib}Gi"},
                "limits": {
                    "cpu": f"{max(default_cpu_millicores * 2, 1000)}m",
                    "memory": f"{mem_gib * 2}Gi",
                },
            },
            "primaryStorage": {
                "defaultSize": f"{default_storage_size_gib}Gi",
                "minSize": f"{min_storage_size_gib}Gi",
                "maxSize": f"{max_storage_size_gib}Gi",
                "defaultStorageClassName": "sagemaker-spaces-default-storage-class",
                "defaultMountPath": PRIMARY_MOUNT_PATH,
            },
            "defaultContainerConfig": {"command": [entrypoint]},
            "defaultPodSecurityContext": {"fsGroup": 1000},
            # Public: 非 owner (管理员等) 也能操作开发机。Workspace 级可 override。
            "defaultOwnershipType": "Public",
            "defaultAccessStrategy": {
                "name": "hyperpod-access-strategy",
                "namespace": "jupyter-k8s-system",
            },
            "allowSecondaryStorages": allow_secondary_storages,
            "appType": app_type,
        },
    }


def render_connection_cr(
    *,
    workspace_name: str = "demo-workspace",
    # default 取集群里一定存在的 team namespace · 给 CR compliance dry-run 用
    namespace: str = "hyperpod-ns-team-a-nlp",
    connection_type: str = "vscode-remote",
    generate_name_prefix: str | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """渲染 WorkspaceConnection (aggregated API, POST-only).

    官方文档 唯一支持的 connection_type 是 vscode-remote.
    server 回填 status.workspaceConnectionUrl → VSCode deep link.

    Args:
        generate_name_prefix: 默认 "{workspace_name}-conn-".
            server 会补随机后缀 (推荐用 generateName 避重名).
    """
    gn_prefix = generate_name_prefix or f"{workspace_name}-conn-"
    meta_labels: dict[str, str] = dict(labels or {})
    # 默认打两个人性化 label
    meta_labels.setdefault("hyperpod-ui/workspace-name", workspace_name)
    meta_labels.setdefault("hyperpod-ui/connection-type", connection_type)

    return {
        "apiVersion": CONNECTION_API_VERSION,
        "kind": CONNECTION_KIND,
        "metadata": {
            "generateName": gn_prefix,
            "namespace": namespace,
            "labels": meta_labels,
        },
        "spec": {
            "workspaceName": workspace_name,
            "workspaceConnectionType": connection_type,
        },
    }


def build_security_context(
    primary_gid: int | None,
    supplemental_gids: list[int] | None = None,
) -> dict[str, Any]:
    """primary_gid / supplemental_gids → containerSecurityContext + podSecurityContext。

    primary_gid None (ws 没挂过 FSx 也没勾 share 目录) → 返空 dict (不覆盖 template
    default 的 fsGroup 1000)。改规格清空挂载时需要恢复默认, 由调用方对空结果显式下发
    null (merge-patch 删 key) 处理。

    把 runAsGroup / supplementalGroups 放在 containerSecurityContext (只作用于主容器
    workspace), 不放 podSecurityContext — 后者是 Pod 级, 会影响 sidecar
    (ssm-agent-sidecar 镜像 /var/log 只 root 可写, register-ssm.sh 起手 tee
    /var/log/... 会 Permission denied)。fsGroup 必须放 podSecurityContext
    (K8s chown volume root dir 是 Pod 级语义)。CRD 字段名 containerSecurityContext +
    podSecurityContext, operator reconcile 时分别映射到 containers[i].securityContext +
    spec.securityContext。
    """
    if primary_gid is None:
        return {}
    all_gids = sorted(set([primary_gid, *(supplemental_gids or [])]))
    return {
        "containerSecurityContext": {
            "runAsUser": 1000,
            "runAsGroup": primary_gid,
        },
        "podSecurityContext": {
            "fsGroup": primary_gid,
            "supplementalGroups": all_gids,
        },
    }


def build_volumes(volume_mounts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """volume_mounts (dict 列表) → spec.volumes[]。空 → 空列表。

    改规格全量替换语义: 传 [] 即清空挂载 (merge-patch 数组整体覆盖)。
    """
    return [_build_volume_entry(vm) for vm in (volume_mounts or [])]


def _build_volume_entry(vm: dict[str, Any]) -> dict[str, Any]:
    """volume_mount dict → spec.volumes[] 一项."""
    entry: dict[str, Any] = {
        "name": vm.get("name") or _slug_volume_name(vm["mount_path"]),
        "mountPath": vm["mount_path"],
        "persistentVolumeClaimName": vm["pvc_name"],
    }
    sub_path = vm.get("sub_path")
    if sub_path:
        entry["subPath"] = sub_path
    return entry


def _slug_volume_name(mount_path: str) -> str:
    """mount_path → K8s 合规 volume name (vm-shared-data 这种).

    K8s name 规范: 小写字母数字 hyphen, ≤63 char.
    /shared/data        → vm-shared-data
    /opt/ml/checkpoint  → vm-opt-ml-checkpoint
    """
    import re
    s = mount_path.strip("/").replace("/", "-").lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)[:60]
    return f"vm-{s}"
