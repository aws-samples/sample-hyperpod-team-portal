"""HyperPodPyTorchJob CR 渲染器 · 纯函数, 严格对齐 AWS 官方 spec.

Sources (authoritative, snapshot 2026-05-12):
    - https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-eks-operator-usage.html
    - `kubectl get crd hyperpodpytorchjobs.sagemaker.amazonaws.com -o json`

Key invariants (一旦违反就会被官方 ValidatingAdmissionPolicy 拒绝):
    - `apiVersion: sagemaker.amazonaws.com/v1` + `kind: HyperPodPyTorchJob`
    - `spec.nprocPerNode`: **string** (auto|cpu|gpu|<int>)
    - `spec.replicaSpecs[].name`: required (replicaSpec 唯一强制字段)
    - `spec.runPolicy.cleanPodPolicy`: enum All|OnlyComplete|None, default "All"
    - `spec.runPolicy.ttlSecondsAfterFinished`: -1 永不 GC, 默认 -1 (产品决策)
    - `spec.runPolicy.jobMaxRetryCount`: 默认 2
    - `spec.runPolicy.restartPolicy.evalPeriodSeconds`: CRD required (给 3600)
    - Container port 8080: HyperPodElasticAgent 监听口, 不要改

Design:
    - 纯函数, 无 IO · 测试可直接调
    - 入参是扁平化的 primitives (str/int/dict) · 与 ORM 解耦, 合规测试也可直接用
    - runPolicy 子字段用可选入参覆盖, 默认全部对齐官方样板
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import t
from app.core.labels import sanitize_label_value
from app.core.priority_defaults import default_priority_class
from app.modules.training.domain.hyperpodrun import wrap_with_hyperpodrun

# 官方 apiVersion + kind · 常量外露供测试使用
HPJ_API_VERSION = "sagemaker.amazonaws.com/v1"
HPJ_KIND = "HyperPodPyTorchJob"

# runPolicy 默认值 · 与 CR 样板 + 产品决策对齐
# K8s 语义: All=都清 / OnlyComplete=成功才清 / None=不清
# PoC debug 期默 None: Pod 训完不清 → 实时日志 SSE/CW 都能拿, 失败现场可 exec 排查.
# 生产改 OnlyComplete (失败 Pod 留, 成功 Pod 走 CW Logs Insights).
_DEFAULT_CLEAN_POD_POLICY = "All"  # 结束清全部 Pod (与前端 runPolicy 编辑框默认对齐)
_DEFAULT_TTL_SECONDS_AFTER_FINISHED = -1
_DEFAULT_JOB_MAX_RETRY_COUNT = 0
_DEFAULT_NUM_RESTART_BEFORE_FULL_JOB_RESTART = 3
_DEFAULT_EVAL_PERIOD_SECONDS = 3600
_DEFAULT_MAX_FULL_JOB_RESTARTS = 1

# Container 常量
_TRAINER_CONTAINER_NAME = "trainer"
_AGENT_CONTAINER_PORT = 8080

# S3 数据集挂载 (mountpoint-s3-csi) 固定 gid 1001; 训练 pod 加进 supplementalGroups
# 才能读 S3 卷 (S3 mount 的文件属 1001 组).
_S3_MOUNT_GID = 1001

# Pod ServiceAccount · ws 创建时建, 通过 EKS Pod Identity 关联 platform-pod-role,
# 给 init container `aws s3 sync` + 容器内 boto3 提供凭证.
# 与 app/adapters/k8s/workspace_resources.py SA_NAME 保持一致.
_WORKSPACE_SA_NAME = "workspace-default"

# 默认 NCCL 环境变量 (用户未覆盖时注入)
_NCCL_DEFAULT_ENV: dict[str, str] = {
    "NCCL_DEBUG": "INFO",
    "NCCL_ASYNC_ERROR_HANDLING": "1",
    "PYTHONUNBUFFERED": "1",
}

# EFA 环境变量 (efa_per_node>0 时注入), 让 NCCL 经 aws-ofi-nccl 走 EFA RDMA
_EFA_ENV: dict[str, str] = {
    "FI_PROVIDER": "efa",
    "FI_EFA_USE_DEVICE_RDMA": "1",
}

# Downward API 环境变量 (无条件注入), 值由 kubelet 运行时填.
# 训练脚本靠 NODE_NAME 知道自己落在哪台机 (打点 / 与 DCGM 的 Hostname、node-exporter
# 的 node label 做 join); 容器内 `hostname` 拿到的是 pod 名, 没有别的途径拿节点名.
_DOWNWARD_ENV: dict[str, str] = {
    "NODE_NAME": "spec.nodeName",
    "POD_NAME": "metadata.name",
}


def _build_resources(
    cpu_millicores: int,
    memory_mib: int,
    gpu_per_node: int,
    efa_per_node: int = 0,
) -> dict[str, Any]:
    """Pod container.resources · requests == limits (HPJ 单实例即稳定).

    efa_per_node>0 才渲 vpc.amazonaws.com/efa (EFA device plugin 暴露的高速网卡资源,
    多节点 NCCL over EFA 用); 0 时不加, CR 与无 EFA 时一致.
    """
    block = {
        "cpu": f"{cpu_millicores}m",
        "memory": f"{memory_mib}Mi",
    }
    if gpu_per_node > 0:
        block["nvidia.com/gpu"] = str(gpu_per_node)
    if efa_per_node > 0:
        block["vpc.amazonaws.com/efa"] = str(efa_per_node)
    return {"requests": dict(block), "limits": dict(block)}


def _build_env(
    user_env: dict[str, str] | None,
    efa_per_node: int = 0,
    env_secrets: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """env 合并 · 用户显式传的优先, 缺的由默认补齐.

    efa_per_node>0 时把 EFA env 并入默认池 (让 NCCL 经 aws-ofi-nccl 走 EFA RDMA,
    前提: 镜像装了 aws-ofi-nccl + libfabric)。同样用户优先 (用户填了同名 key 不覆盖)。

    env_secrets: 每项 {name, secret_ref, secret_key} → 渲 valueFrom.secretKeyRef。

    NODE_NAME / POD_NAME 走 Downward API (valueFrom.fieldRef) 无条件注入, 同样用户优先。

    注: 不能注入 JOB_NAME — HyperPod Training Operator 保留该变量, 用户设会被
    admission webhook (vhyperpodpytorchjob.kb.io) 拒 403。operator 自己注入 JOB_NAME,
    inline 脚本里直接用 ${JOB_NAME} 即可 (operator 运行时给)。
    """
    user_env = user_env or {}
    defaults = {**_NCCL_DEFAULT_ENV, **(_EFA_ENV if efa_per_node > 0 else {})}
    env: list[dict[str, Any]] = [{"name": k, "value": v} for k, v in user_env.items()]
    for k, v in defaults.items():
        if k not in user_env:
            env.append({"name": k, "value": v})
    # Downward API · 同 defaults 的"用户优先"约定, 但逐项判断: 用户只传了 POD_NAME
    # 时 NODE_NAME 仍然注入, 不整体跳过。
    for name, field_path in _DOWNWARD_ENV.items():
        if name not in user_env:
            env.append(
                {"name": name, "valueFrom": {"fieldRef": {"fieldPath": field_path}}}
            )
    for s in env_secrets or []:
        env.append(
            {
                "name": s["name"],
                "valueFrom": {
                    "secretKeyRef": {"name": s["secret_ref"], "key": s["secret_key"]}
                },
            }
        )
    return env


class RunPolicyValidationError(ValueError):
    """用户提交的 run_policy_override 非法 (越权字段 / 缺 required / 类型错)。

    orchestration 层捕获 → 转 HTTP 422, 把 message 透给前端提示用户。
    """


# run_policy_override 白名单 · 用户只能填这些字段 (编辑范围 A: 只 runPolicy 段)。
# 顶层 / restartPolicy 内各自的合法 key + 期望类型, 其余键拒绝 (防越权 / 注入)。
_RUN_POLICY_TOP_INT_KEYS = (
    "ttlSecondsAfterFinished",
    "jobMaxRetryCount",
    "activeDeadlineSeconds",
)
_RESTART_POLICY_INT_KEYS = (
    "numRestartBeforeFullJobRestart",
    "evalPeriodSeconds",
    "maxFullJobRestarts",
)
_CLEAN_POD_POLICY_ENUM = ("All", "OnlyComplete", "None")

# logMonitoringConfiguration · 官方 runPolicy 数组字段 (日志监控规则, 检测 hang/slow)。
# 每项子字段白名单 + 类型 (官方: sagemaker-eks-operator-usage.html)。
_LOG_MON_STR_KEYS = ("name", "logPattern", "stopPattern")
_LOG_MON_INT_KEYS = (
    "expectedStartCutOffInSeconds",
    "expectedRecurringFrequencyInSeconds",
    "metricEvaluationDataPoints",
)
_LOG_MON_OPERATOR_ENUM = ("gt", "gteq", "lt", "lteq", "eq")

# 用户填了非官方字段时, 错误消息附官方文档链接, 引导对照。
_RUN_POLICY_DOC_URL = (
    "https://docs.aws.amazon.com/sagemaker/latest/dg/"
    "sagemaker-eks-operator-usage.html"
)


def _require_int(field: str, value: Any) -> int:
    """校验/规整为 int (排除 bool · bool 是 int 子类, retry=true 不合理)。

    宽容数字字符串 ("-1" / "3"): 克隆链路 yaml.dump→load 会把数字 override 转成
    带引号的字符串存进 DDB, 再克隆透传过来即字符串。语义上 '-1' 与 -1 等价, 这里
    统一转 int, 避免"任务已建成功却因字符串 ttl 二次校验 500"。非数字才报错。
    """
    if isinstance(value, bool):
        raise RunPolicyValidationError(
            t("training.run_policy.int_bool", field=field, value=repr(value))
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (ValueError, AttributeError):
            pass
    raise RunPolicyValidationError(
        t(
            "training.run_policy.int_type",
            field=field,
            type=type(value).__name__,
            value=repr(value),
        )
    )


def _validate_log_monitoring(items: Any) -> list[dict[str, Any]]:
    """校验 runPolicy.logMonitoringConfiguration (官方数组字段)。

    每项: name/logPattern/stopPattern(str) + 三个 *Seconds/DataPoints(int) +
    metricThreshold(number) + operator(enum) + faultOnMatch(bool)。白名单 + 类型。
    """
    if not isinstance(items, list):
        raise RunPolicyValidationError(
            t("training.run_policy.log_mon_not_list", type=type(items).__name__)
        )
    allowed = {
        *_LOG_MON_STR_KEYS,
        *_LOG_MON_INT_KEYS,
        "metricThreshold",
        "operator",
        "faultOnMatch",
    }
    cleaned: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise RunPolicyValidationError(
                t(
                    "training.run_policy.log_mon_item_not_object",
                    idx=idx,
                    type=type(item).__name__,
                )
            )
        unknown = set(item) - allowed
        if unknown:
            raise RunPolicyValidationError(
                t(
                    "training.run_policy.log_mon_item_unknown",
                    idx=idx,
                    unknown=sorted(unknown),
                    allowed=sorted(allowed),
                    doc_url=_RUN_POLICY_DOC_URL,
                )
            )
        rule: dict[str, Any] = {}
        for k in _LOG_MON_STR_KEYS:
            if k in item:
                if not isinstance(item[k], str):
                    raise RunPolicyValidationError(
                        t("training.run_policy.log_mon_not_str", idx=idx, key=k)
                    )
                rule[k] = item[k]
        for k in _LOG_MON_INT_KEYS:
            if k in item:
                rule[k] = _require_int(
                    f"logMonitoringConfiguration[{idx}].{k}", item[k]
                )
        if "metricThreshold" in item:
            mt = item["metricThreshold"]
            if isinstance(mt, bool) or not isinstance(mt, (int, float)):
                raise RunPolicyValidationError(
                    t("training.run_policy.log_mon_threshold_not_number", idx=idx)
                )
            rule["metricThreshold"] = mt
        if "operator" in item:
            op = item["operator"]
            if op not in _LOG_MON_OPERATOR_ENUM:
                raise RunPolicyValidationError(
                    t(
                        "training.run_policy.log_mon_bad_operator",
                        idx=idx,
                        allowed=list(_LOG_MON_OPERATOR_ENUM),
                        value=repr(op),
                    )
                )
            rule["operator"] = op
        if "faultOnMatch" in item:
            if not isinstance(item["faultOnMatch"], bool):
                raise RunPolicyValidationError(
                    t("training.run_policy.log_mon_fault_not_bool", idx=idx)
                )
            rule["faultOnMatch"] = item["faultOnMatch"]
        cleaned.append(rule)
    return cleaned


def _validate_run_policy(override: dict[str, Any]) -> dict[str, Any]:
    """校验用户整段 runPolicy override, 返回清洗后可直接进 CR 的 dict。

    规则:
    - 白名单: 顶层只允许 cleanPodPolicy + _RUN_POLICY_TOP_INT_KEYS + restartPolicy
      + logMonitoringConfiguration; restartPolicy 内只允许 _RESTART_POLICY_INT_KEYS;
      logMonitoringConfiguration 每项子字段另有白名单; 其余键 raise (防越权)。
    - 类型: 整数字段必须 int (排除 bool); cleanPodPolicy / operator 必须在 enum。
    - 补 CRD required: restartPolicy.evalPeriodSeconds 缺则补默认 (CRD 强制);
      override 无 restartPolicy 整段时补默认整段。

    官方字段参考: docs.aws.amazon.com sagemaker-eks-operator-usage.html。
    注: ttlSecondsAfterFinished / activeDeadlineSeconds 官方文档未列, 但 CRD 实际
    接受 (平台默认逻辑一直在用), 故仍纳入白名单。
    """
    if not isinstance(override, dict):
        raise RunPolicyValidationError(
            t("training.run_policy.not_object", type=type(override).__name__)
        )

    allowed_top = {
        "cleanPodPolicy",
        "restartPolicy",
        "logMonitoringConfiguration",
        *_RUN_POLICY_TOP_INT_KEYS,
    }
    unknown_top = set(override) - allowed_top
    if unknown_top:
        raise RunPolicyValidationError(
            t(
                "training.run_policy.unknown_fields",
                unknown=sorted(unknown_top),
                allowed=sorted(allowed_top),
                doc_url=_RUN_POLICY_DOC_URL,
            )
        )

    cleaned: dict[str, Any] = {}

    if "cleanPodPolicy" in override:
        cpp = override["cleanPodPolicy"]
        if cpp not in _CLEAN_POD_POLICY_ENUM:
            raise RunPolicyValidationError(
                t(
                    "training.run_policy.bad_clean_pod_policy",
                    allowed=list(_CLEAN_POD_POLICY_ENUM),
                    value=repr(cpp),
                )
            )
        cleaned["cleanPodPolicy"] = cpp

    for key in _RUN_POLICY_TOP_INT_KEYS:
        if key in override:
            cleaned[key] = _require_int(key, override[key])

    # restartPolicy: evalPeriodSeconds 是 CRD required, 缺则补默认
    rp_in = override.get("restartPolicy")
    if rp_in is not None:
        if not isinstance(rp_in, dict):
            raise RunPolicyValidationError(
                t("training.run_policy.restart_not_object", type=type(rp_in).__name__)
            )
        unknown_rp = set(rp_in) - set(_RESTART_POLICY_INT_KEYS)
        if unknown_rp:
            raise RunPolicyValidationError(
                t(
                    "training.run_policy.restart_unknown_fields",
                    unknown=sorted(unknown_rp),
                    allowed=sorted(_RESTART_POLICY_INT_KEYS),
                    doc_url=_RUN_POLICY_DOC_URL,
                )
            )
        rp_clean: dict[str, Any] = {}
        for key in _RESTART_POLICY_INT_KEYS:
            if key in rp_in:
                rp_clean[key] = _require_int(f"restartPolicy.{key}", rp_in[key])
        rp_clean.setdefault("evalPeriodSeconds", _DEFAULT_EVAL_PERIOD_SECONDS)
        cleaned["restartPolicy"] = rp_clean
    else:
        cleaned["restartPolicy"] = {
            "numRestartBeforeFullJobRestart": _DEFAULT_NUM_RESTART_BEFORE_FULL_JOB_RESTART,
            "evalPeriodSeconds": _DEFAULT_EVAL_PERIOD_SECONDS,
            "maxFullJobRestarts": _DEFAULT_MAX_FULL_JOB_RESTARTS,
        }

    if "logMonitoringConfiguration" in override:
        cleaned["logMonitoringConfiguration"] = _validate_log_monitoring(
            override["logMonitoringConfiguration"]
        )

    return cleaned


def _build_run_policy(
    clean_pod_policy: str = _DEFAULT_CLEAN_POD_POLICY,
    ttl_seconds_after_finished: int = _DEFAULT_TTL_SECONDS_AFTER_FINISHED,
    job_max_retry_count: int = _DEFAULT_JOB_MAX_RETRY_COUNT,
    active_deadline_seconds: int | None = None,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """官方 spec.runPolicy · restartPolicy.evalPeriodSeconds 是 CRD required.

    override 非 None 时整段覆盖 (经 _validate_run_policy 校验); 否则逐字段拼默认。
    """
    if override is not None:
        return _validate_run_policy(override)
    run_policy: dict[str, Any] = {
        "cleanPodPolicy": clean_pod_policy,
        "ttlSecondsAfterFinished": ttl_seconds_after_finished,
        "jobMaxRetryCount": job_max_retry_count,
        "restartPolicy": {
            "numRestartBeforeFullJobRestart": _DEFAULT_NUM_RESTART_BEFORE_FULL_JOB_RESTART,
            "evalPeriodSeconds": _DEFAULT_EVAL_PERIOD_SECONDS,
            "maxFullJobRestarts": _DEFAULT_MAX_FULL_JOB_RESTARTS,
        },
    }
    if active_deadline_seconds is not None:
        run_policy["activeDeadlineSeconds"] = active_deadline_seconds
    return run_policy


def _build_volumes_and_mounts(
    s3_datasets: list[dict[str, str]] | None,
    extra_fsx_mounts: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """渲染 volumes + volumeMounts (FSx 全平等挂载, 无 /fsx 主盘).

    挂载策略:
    - /dev/shm tmpfs 2Gi (NCCL inter-rank 共享内存; Docker 默 64Mi 撑爆 4-rank)
    - S3 PVC (mountpoint-s3-csi) → mount_path (只读)
    - FSx (extra_fsx_mounts): 该 user 被授权的盘, 各自 pvc → 授权 mount_path
      (read_only 来自授权). 路径/权限授权时已定, 训练侧只透传. 代码/checkpoint
      路径由用户在启动脚本按挂载路径自己写.
    """
    # NCCL 段经 /dev/shm 通信 (g6 无 NVLink, 走 SHM 回落). 默 64Mi 不够,
    # 触发 `failed to extend /dev/shm/nccl-XXXX → ncclSystemError`.
    volumes: list[dict[str, Any]] = [
        {
            "name": "dshm",
            "emptyDir": {"medium": "Memory", "sizeLimit": "2Gi"},
        }
    ]
    mounts: list[dict[str, Any]] = [{"name": "dshm", "mountPath": "/dev/shm"}]

    for idx, ds in enumerate(s3_datasets or []):
        # pvc_name 来自 ws S3 挂载真值 (pvc-ws-s3-{mount_id}, orchestration 反查填入)。
        # 兼容旧数据 (无 pvc_name) 回退 s3-{bucket}。
        pvc_name = ds.get("pvc_name") or f"s3-{ds['bucket'][:40]}"
        vol_name = f"s3-ds-{idx}"
        volumes.append(
            {"name": vol_name, "persistentVolumeClaim": {"claimName": pvc_name}}
        )
        mounts.append(
            {"name": vol_name, "mountPath": ds["mount_path"], "readOnly": True}
        )

    # 额外 FSx (跨 ws 共享盘, 该 user 被授权): 各自 PVC 挂到授权定的 mount_path.
    # pvc_name / mount_path / read_only 来自 shared-pvcs (MountPermissions), 训练侧只透传.
    for idx, m in enumerate(extra_fsx_mounts or []):
        vol_name = f"xfsx-{idx}"
        volumes.append(
            {
                "name": vol_name,
                "persistentVolumeClaim": {"claimName": m["pvc_name"]},
            }
        )
        mounts.append(
            {
                "name": vol_name,
                "mountPath": m["mount_path"],
                "readOnly": bool(m.get("read_only", True)),
            }
        )

    # 注: 代码不单独挂载. 代码/数据/checkpoint 在用户选的某个 FSx 挂载路径下,
    # 路径由用户在启动脚本自己写 ( 读写权限由授权 ro/rw 限制)。

    return volumes, mounts


def render_hp_pytorch_job_cr(
    *,
    name: str,
    namespace: str,
    image: str,
    command: str,
    node_count: int,
    spares: int = 0,
    gpu_per_node: int,
    cpu_per_node_millicores: int,
    memory_per_node_mib: int,
    efa_per_node: int = 0,
    # 可选 · 业务上下文 (全进 metadata.labels)
    training_job_id: str | None = None,
    workspace_id: str | None = None,
    creator_id: str | None = None,
    experiment_id: str | None = None,
    # 可选 · Kueue 优先级 (统一默认 common-priority=80, 产品决策 2026-06-11;
    # 三类任务 dev/train/inference 同档, 差异化靠优先级管理页手调)
    priority_class: str | None = None,
    env: dict[str, str] | None = None,
    # 从 Secret 注入的 env (每项 {name, secret_ref, secret_key} → secretKeyRef)
    env_secrets: list[dict[str, str]] | None = None,
    # 可选 · 代码位置 (仅记录, 不产生挂载; 用户在启动脚本按挂载路径引用)
    code: dict[str, str] | None = None,  # noqa: ARG001 透传记录, 挂载靠 extra_fsx_mounts
    # FSx 全平等挂载 (extra_fsx_mounts), 无 /fsx 主盘特殊语义。
    # run_as_group = ws primary_gid 兜底 (securityContext runAsGroup/fsGroup)。
    # fsx_supplemental_gids = 所有选中 FSx 的 gid (进 supplementalGroups, + S3 1001)。
    run_as_group: int | None = None,
    fsx_supplemental_gids: list[int] | None = None,
    s3_datasets: list[dict[str, str]] | None = None,
    extra_fsx_mounts: list[dict[str, Any]] | None = None,
    # 可选 · 实例类型: 写 pod nodeSelector node.kubernetes.io/instance-type,
    # 锁该机型 → Kueue 选对应 flavor → 调度到对应资源池。空则不写 (走 Kueue 自动分)。
    instance_type: str | None = None,
    # 可选 · runPolicy 覆盖 (默认对齐官方样板 + 产品决策)
    clean_pod_policy: str = _DEFAULT_CLEAN_POD_POLICY,
    ttl_seconds_after_finished: int = _DEFAULT_TTL_SECONDS_AFTER_FINISHED,
    job_max_retry_count: int = _DEFAULT_JOB_MAX_RETRY_COUNT,
    active_deadline_seconds: int | None = None,
    # 可选 · runPolicy 整段覆盖 (用户 step5 编辑, 经 _validate_run_policy 校验)。
    # 非 None 时忽略上面 4 个 runPolicy 字段, 整段用 override。
    run_policy_override: dict[str, Any] | None = None,
    # 可选 · Kueue TAS 拓扑感知调度 (g6 不支持, p5+/trn 才生效)
    topology_mode: str = "none",
    topology_label: str | None = None,
    # 可选 · 平台是否自动套 hyperpodrun。默认 False = 透传用户 command 原样
    # (用户自己写 hyperpodrun/pip/log, 透明可控)。True 才走 wrap_with_hyperpodrun 套壳。
    auto_wrap: bool = False,
    # 用户自定义 label: 已经 validate_user_labels 校验; 平台 label 后写覆盖同名。
    user_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Render a HyperPodPyTorchJob CR dict strictly per AWS official spec.

    纯函数 · 不依赖 ORM row · 合规测试可直接调.

    Args 命名对齐 CR 样板 snake_case -> camelCase 的 Python 侧习惯. 字段语义

    Returns:
        dict[str, Any]: 可直接喂给 ``CustomObjectsApi.create_namespaced_custom_object``
        的 CR body, 或 ``kubectl apply -f -`` 的 YAML 等价.
    """
    if priority_class is None:
        priority_class = default_priority_class("train")
    queue_name = f"{namespace}-localqueue"

    # 标签聚合: 用户自定义 + 业务追溯 + Kueue 排队所需。
    # user_labels 先写, 平台/Kueue label 后写覆盖同名 (黑名单已挡保留前缀, 双保险)。
    labels: dict[str, str] = {
        **(user_labels or {}),
        "kueue.x-k8s.io/queue-name": queue_name,
        "kueue.x-k8s.io/priority-class": priority_class,
    }
    if training_job_id is not None:
        labels["platform.hyperpod.io/training-job-id"] = training_job_id
    if workspace_id is not None:
        labels["platform.hyperpod.io/workspace-id"] = workspace_id
    if creator_id is not None:
        # creator_id 可能是邮箱格式 username (含 @), 合法化成 K8s label value 否则 422
        labels["platform.hyperpod.io/creator-id"] = sanitize_label_value(creator_id, fallback="unknown")
    if experiment_id is not None:
        labels["platform.hyperpod.io/experiment-id"] = experiment_id

    # Pod template labels · 业务追溯 + 用户自定义 label, Kueue label 不复制 (operator 自注入).
    # Fluent Bit 抓 Pod (非 CR) labels 写到 CW JSON `kubernetes.labels` 字段;
    # CW Logs Insights query 用 training_job_id 反查必须有 Pod label.
    pod_labels: dict[str, str] = {**(user_labels or {})}
    if training_job_id is not None:
        pod_labels["platform.hyperpod.io/training-job-id"] = training_job_id
    if workspace_id is not None:
        pod_labels["platform.hyperpod.io/workspace-id"] = workspace_id
    if creator_id is not None:
        pod_labels["platform.hyperpod.io/creator-id"] = sanitize_label_value(creator_id, fallback="unknown")
    if experiment_id is not None:
        pod_labels["platform.hyperpod.io/experiment-id"] = experiment_id

    # 训练日志全量归档: 挂了 FSx 时, hyperpodrun --log_dir 落到 FSx (持久, 每 rank 一文件),
    # pod 删后日志仍在 /fsx/outputs/<job>/logs. 没挂 FSx 则默 /tmp (临时, 随 pod 删).
    # checkpoint 同盘 (/fsx/outputs/<job>/), 训练产物集中. (日志 tab 看实时 CloudWatch;
    # FSx 这份是完整原始归档, 解决长任务 CloudWatch 10000 行/1h 窗查不全的问题.)
    # command 形态:
    #   list[str] (如 ["bash","/fsx/x.sh"]): exec 数组, 仅 auto_wrap=False 出现 →
    #       原样进 YAML command (透明形式, 不包 -lc, 不套壳)。
    #   str: 单串 → auto_wrap=False 时 /bin/bash -lc 跑; True 时套 hyperpodrun。
    if isinstance(command, list):
        # 透传 exec 数组, 平台零加工 (auto_wrap 对数组形式无意义, 前端不会同时给)。
        container_command = list(command)
    elif not auto_wrap:
        # 默认: 透传用户 command 原样, 平台不套壳 (用户自管 hyperpodrun/pip/log)。
        container_command = ["/bin/bash", "-lc", command]
    else:
        # 无 /fsx 主盘特殊语义, 不再自动拼 FSx log_dir。
        # auto_wrap=True 时套 hyperpodrun (用户自管 log 路径; 默认 auto_wrap=False)。
        wrapped_command = wrap_with_hyperpodrun(command, gpu_per_node)
        container_command = ["/bin/bash", "-lc", wrapped_command]
    # nprocPerNode 官方要 string
    nproc_per_node = str(gpu_per_node) if gpu_per_node > 0 else "1"

    resources = _build_resources(
        cpu_per_node_millicores, memory_per_node_mib, gpu_per_node, efa_per_node
    )
    container_env = _build_env(env, efa_per_node, env_secrets)

    run_policy = _build_run_policy(
        clean_pod_policy=clean_pod_policy,
        ttl_seconds_after_finished=ttl_seconds_after_finished,
        job_max_retry_count=job_max_retry_count,
        active_deadline_seconds=active_deadline_seconds,
        override=run_policy_override,
    )

    volumes, mounts = _build_volumes_and_mounts(
        s3_datasets=s3_datasets,
        extra_fsx_mounts=extra_fsx_mounts,
    )

    pod_spec: dict[str, Any] = {
        "serviceAccountName": _WORKSPACE_SA_NAME,
        "containers": [
            {
                "name": _TRAINER_CONTAINER_NAME,
                "image": image,
                "imagePullPolicy": "IfNotPresent",
                "command": container_command,
                "ports": [{"containerPort": _AGENT_CONTAINER_PORT}],
                "resources": resources,
                "env": container_env,
                "volumeMounts": mounts,
            }
        ],
    }
    if volumes:
        pod_spec["volumes"] = volumes

    # 实例类型 → nodeSelector 锁机型 (Kueue 据此选对应 flavor 落对应池)。
    # 实测 (2026-06-16): CPU 任务选 m5 → Kueue 选 m5 flavor + 落 m5 节点, 不跟 Kueue 冲突。
    # 空 instance_type 则不写 (走 Kueue 自动分, 兼容旧任务)。
    if instance_type:
        pod_spec["nodeSelector"] = {
            "node.kubernetes.io/instance-type": instance_type
        }

    # securityContext: 挂了 FSx 时设组身份, 让训练写的文件 team 同组可读写 (开发机同 gid
    # 直接访问日志/checkpoint, 不用 sudo).
    # ★runAsUser=0 (root): containerd 要求设了 runAsGroup 必须有 runAsUser
    #   ("user group X specified without user" 否则拒建 sandbox → ContainerCreating 卡死).
    #   训练镜像 (pytorch) 本就 root, 无 uid 1000/1001 用户 (设非 root 会 getpwuid/HOME/pip 崩,
    #   实测 uid 1001 HOME=/root 写不了 → pip/缓存踩雷). 故用 root=0.
    #   文件归属: owner=root(0), group=run_as_group(team) → 开发机【同 team 组】仍可访问
    #   (靠 group 不靠 owner; runAsGroup 让新建文件主组=team).
    # run_as_group = ws primary_gid 兜底 (第一个 FSx gid)。fsGroup 同。
    # supplementalGroups = 所有选中 FSx 的 gid + S3 固定 1001 (让训练读写各授权盘/读 S3)。
    if run_as_group is not None:
        supp = sorted(set([*(fsx_supplemental_gids or []), _S3_MOUNT_GID]))
        pod_spec["securityContext"] = {
            "runAsUser": 0,
            "runAsGroup": run_as_group,
            "fsGroup": run_as_group,
            "fsGroupChangePolicy": "OnRootMismatch",
            "supplementalGroups": supp,
        }

    return {
        "apiVersion": HPJ_API_VERSION,
        "kind": HPJ_KIND,
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "nprocPerNode": nproc_per_node,
            "runPolicy": run_policy,
            "replicaSpecs": [
                {
                    "name": "pods",
                    "replicas": node_count,
                    "spares": spares,
                    # template.metadata.labels 只复制业务追溯 label (training_job_id 等).
                    # Kueue queue / priority-class 不复制 - operator 从 CR metadata.labels
                    # 自注入到 Pod, 写两处会漂移.
                    # template.metadata.annotations: Kueue TAS 拓扑约束 (仅 p5+/trn 生效).
                    "template": {
                        **_build_template_metadata(
                            pod_labels, topology_mode, topology_label
                        ),
                        "spec": pod_spec,
                    },
                }
            ],
        },
    }


def _build_template_metadata(
    pod_labels: dict[str, str],
    topology_mode: str,
    topology_label: str | None,
) -> dict[str, Any]:
    """渲染 replicaSpec.template.metadata block (labels + Kueue TAS annotations).

    Kueue TAS annotations:
    - kueue.x-k8s.io/podset-required-topology  (mode=required)
    - kueue.x-k8s.io/podset-preferred-topology (mode=preferred)
    g6 节点不在 TAS 支持列表 (p5+/trn 才生效); 加了 g6 也静默忽略, 不报错.
    """
    annotations: dict[str, str] = {}
    if topology_mode in ("required", "preferred") and topology_label:
        ann_key = f"kueue.x-k8s.io/podset-{topology_mode}-topology"
        annotations[ann_key] = topology_label

    md: dict[str, Any] = {}
    if pod_labels:
        md["labels"] = pod_labels
    if annotations:
        md["annotations"] = annotations
    if not md:
        return {}
    return {"metadata": md}
