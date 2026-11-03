"""TrainingJob Pydantic Schemas (DDB-only —)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.i18n import t
from app.core.priority_defaults import default_priority_class

CleanPodPolicy = Literal["All", "OnlyComplete", "None"]


class CodeSourceFsx(BaseModel):
    """FSx 代码源 · 仅记录代码在 FSx 上的位置 (不产生独立挂载).

    整块 FSx (顶层 fsx_pvc, step1 选的 FSx 路径) 挂到容器 /fsx (可读写); 代码在
    /fsx/<code_sub_path> 下, 同级训练数据 + checkpoint 输出都在同一块, 一次挂载全可访问.
    本字段只存"代码在哪个子目录 + 启动文件名"供 command 参考, 不单独挂 /code (避免同一
    FSx PV 重复挂载卡死).
    """

    source: Literal["fsx"] = "fsx"
    # 代码在 FSx (挂载点 /fsx) 下的相对子目录 (如 "my-project/src"). 空=fsx 根.
    code_sub_path: str = Field(default="", max_length=512)
    # 启动入口文件名 (相对代码子目录), command 模板里引用
    entrypoint: str | None = None


# 代码源回归只 FSx (github clone/initContainer 已废弃, 代码来源交用户)。
CodeSource = CodeSourceFsx


class EnvSecret(BaseModel):
    """从 k8s Secret 注入的环境变量 (B2 每人一把)。

    值不进 CR 明文 (只有 secretKeyRef 引用)。B2: secret_ref 前端不填, 后端 create 时
    自动补本人固定 secret 名 (<owner>-secrets); detail 回读时带值供克隆。
    """

    name: str = Field(min_length=1, max_length=253)
    secret_key: str = Field(min_length=1, max_length=253)
    secret_ref: str = Field(default="", max_length=253)  # 后端补本人固定名


class S3DatasetRef(BaseModel):
    """训练创建时引用 workspace 已挂的 S3 数据集 (只传 mount_id, 后端查真值)。

    安全: 用户只能选 ws admin 已挂载/授权的 S3 (走 list_workspace_s3_flow),
    不能自由填任意 bucket。后端按 mount_id 反查真实 pvc_name/bucket/mount_path,
    不在 ws 挂载列表 → 403 (API 层卡死越权)。
    """

    mount_id: str = Field(min_length=1, max_length=128)


class S3DatasetMount(BaseModel):
    """S3 数据集挂载 (存储/展示形状, mountpoint-s3-csi 只读)。

    后端从 ws S3 挂载查到真值后填充; pvc_name = ws 挂载建的真 PVC
    (pvc-ws-s3-{mount_id}), CR 渲染直接用它做 claimName。
    """

    bucket: str = Field(min_length=1, max_length=63)
    prefix: str = Field(default="", max_length=512)
    mount_path: str = Field(min_length=1, max_length=255)
    pvc_name: str = Field(default="", max_length=253)


class FsxMountRef(BaseModel):
    """训练创建时引用该 user 被授权的 FSx (只传 pvc_name, 后端反查授权真值)。

    安全: 用户只能选自己在该 ws 被授权的 FSx (MountPermissions
    list_by_user_in_ws)。后端按 pvc_name 反查真实 mount_path / access(ro/rw) /
    gid, 不信前端传的值。pvc_name 不在该 user 授权列表 → 403 (API 层卡死越权)。
    """

    pvc_name: str = Field(min_length=1, max_length=253)


class ExtraFsxMount(BaseModel):
    """FSx 挂载 (存储/展示形状)。后端反查授权后填充真值, CR 渲染直接用。

    pvc_name = 授权记录的 PVC; mount_path / read_only 取自授权 (workspace 层已定)。
    """

    pvc_name: str = Field(min_length=1, max_length=253)
    mount_path: str = Field(min_length=1, max_length=255)
    read_only: bool = True


class TrainingJobCreate(BaseModel):
    # name 由后端从 display_name 派生; 输入侧禁传 (传了 422, 不静默忽略).
    # 仍作响应字段返回真实任务名.
    name: str | None = None
    # display_name 自身必须 DNS 合法: name 是纯拼接不清洗, 非法字符在此拒而非悄悄清洗.
    # 上限 29 = TRAINING_NAME_MAX(40) - 1 - 10随机. 前端有同一条 pattern 做即时提示,
    # 靠 frontend/scripts/check-validation-sync.mjs 防两边漂移.
    display_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]{1,27}[a-z0-9]$",
        description=(
            "任务显示名, 同时作为 K8s 任务名前缀。小写字母开头, 3-29 字符, "
            "只含 a-z 0-9 '-', 结尾须字母或数字。中文说明请写 description。"
        ),
    )

    @field_validator("display_name", mode="before")
    @classmethod
    def _explain_display_name(cls, v: object) -> object:
        """把最常见的两种输错换成人话, 其余仍由 pattern 兜底。

        必须 mode="before": Field(pattern=...) 先跑, 一旦不匹配就抛
        string_pattern_mismatch (只给正则原文), after 阶段根本不会执行。
        判定权仍在 pattern, 这里只负责把报错说清楚, 不放宽也不收紧。
        """
        if isinstance(v, str):
            # 逐字符判可打印 ASCII 而不是 isascii(): 制表符/控制符也是 ASCII, isascii()
            # 会放它过去, 报错就落到 pattern 上只吐正则原文。
            if not all("\x20" <= c <= "\x7e" for c in v):
                raise ValueError(t("core.display_name_ascii"))
            if not 3 <= len(v) <= 29:
                raise ValueError(
                    t("training.display_name_length", actual=len(v))
                )
        return v

    @field_validator("name")
    @classmethod
    def _reject_client_supplied_name(cls, v: str | None) -> None:
        """禁止调用方指定任务名 (唯一性由后端独占保证)。"""
        if v:
            raise ValueError(t("core.name_not_client_supplied"))
        return None
    description: str | None = None
    image: str = Field(min_length=1, max_length=512)
    # str = 单串 (后端 /bin/bash -lc 跑, 或 auto_wrap 套壳)；
    # list[str] = exec 数组 (如 ["bash","/fsx/x.sh"]), auto_wrap=False 时原样进 YAML command。
    command: str | list[str] = Field(min_length=1)
    # node/cpu/mem 不设上限: 真实边界由 ComputeQuota + K8s 调度卡 (申请超容量 → Pending)。
    # 大模型千卡训练 (>125 节点 @8卡) + B300 单节点几百核 TB 内存, 写死上限会拦合法配置。
    node_count: int = Field(default=1, ge=1)
    # ge=0: 允许 CPU-only 训练 (数据预处理/调试/sleep 占位); 0 时 cr.py 不渲 nvidia.com/gpu
    gpu_per_node: int = Field(default=1, ge=0, le=8)
    cpu_per_node_millicores: int = Field(default=2000, ge=100)
    memory_per_node_mib: int = Field(default=8192, ge=512)
    # 每 Pod 申请的 EFA 高速网卡数 (vpc.amazonaws.com/efa). 0 = 不渲此资源 (CR 不变);
    # >0 才进 container.resources. 多节点 NCCL 走 EFA 用; 值按机型 (g6.12x=1) 由用户填.
    efa_per_node: int = Field(default=0, ge=0, le=32)
    env: dict[str, str] = Field(default_factory=dict)
    # 从 Secret 注入的 env (值不明文)
    env_secrets: list[EnvSecret] = Field(default_factory=list)

    clean_pod_policy: CleanPodPolicy = "All"  # 结束清全部 Pod (与前端 runPolicy 默认对齐)
    ttl_seconds_after_finished: int = Field(default=-1, ge=-1, le=2_592_000)
    active_deadline_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    job_max_retry_count: int = Field(default=0, ge=0, le=100)

    # runPolicy 整段覆盖 · 用户在 step5 编辑 runPolicy 裸 YAML, 前端 yaml.load 成 dict 传入。
    # None = 用上面的 clean_pod_policy/ttl/retry 等默认逐字段拼 (现有行为不变)。
    # 非 None = 整段覆盖 spec.runPolicy, 但经后端 _validate_run_policy 白名单 + 补 CRD
    # required (evalPeriodSeconds) + 类型校验 (防裸 YAML 写非法字段 / 越权 / 类型错)。
    run_policy_override: dict[str, Any] | None = None

    # SOW: 实验绑定 (选填) + 优先级 (默 common-priority, 三类任务统一 · 产品决策 2026-06-11)
    experiment_id: str | None = Field(default=None, max_length=64)
    priority_class: str = Field(
        default_factory=lambda: default_priority_class("train"),
        max_length=64,
    )

    # 实例类型: 选 ws ComputeQuota 已分配的机型 (g6/m5 等), 后端校验 ∈ 配额,
    # CR 写 nodeSelector(node.kubernetes.io/instance-type) 锁该机型, 任务调度到对应池。
    # 选填: 缺省不写 nodeSelector (走 Kueue 自动分, 兼容旧任务)。
    instance_type: str | None = Field(default=None, max_length=64)
    # code 代码源: fsx=仅记录位置 (用户在启动脚本按挂载路径引用)。
    # github 代码源已废弃 (代码来源交用户: FSx / 用户脚本 clone), 只留 fsx。
    code: CodeSource | None = None
    # FSx 挂载: 只传 pvc_name 引用该 user 被授权的 FSx, 后端反查授权真值
    # (mount_path / ro-rw / gid)。多选, 各盘按授权 mount_path 平等挂载 (无 /fsx 主盘特殊
    # 语义)。代码/checkpoint 路径由用户在启动脚本自己写, 读写权限由授权 ro/rw 限制。
    # gid: 所有选中 FSx 的 gid 进 supplementalGroups; runAsGroup = ws primary_gid
    # (兜底: 第一个 FSx gid)。S3 用固定 gid 1001 (mountpoint-s3) 也进 supplementalGroups。
    fsx_mounts: list[FsxMountRef] = Field(default_factory=list)
    # S3 挂载: 只传 mount_id 引用 ws 已挂的 S3 (后端查真值, 防自由填越权)。
    s3_datasets: list[S3DatasetRef] = Field(default_factory=list)

    # 拓扑感知调度 (Kueue TAS · 仅 p5+/trn 节点支持, g6 静默忽略)
    # mode: none = 不约束 / preferred = 优先同层降级上层 / required = 必须同层等
    # 额外节点 → replicaSpecs[].spares
    spares: int = Field(default=0, ge=0)

    topology_mode: Literal["none", "preferred", "required"] = "none"
    # 层级名由集群 Topology CR 决定, 不做白名单; 创建时校验 ∈ 该机型可用层级。
    # 316 = K8s label key 上限 (253 + "/" + 63)。
    topology_label: str | None = Field(default=None, max_length=316)

    # 平台是否自动套 hyperpodrun。默认 False = command 原样下发 (用户自管, 透明)。
    # True = 走 wrap_with_hyperpodrun 套壳 (pip agent + log_dir + 防套娃 guard)。
    auto_wrap: bool = False

    # 用户自定义 label: 实验归类, 裸 key, 后端 validate_user_labels 校验。
    labels: dict[str, str] = Field(default_factory=dict)


class TrainingJobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    creator_user_id: str
    creator_display_name: str
    name: str
    display_name: str
    phase: str
    kueue_status: str | None = None  # Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像, informer 写)
    node_count: int
    gpu_per_node: int
    efa_per_node: int = 0
    cpu_per_node_millicores: int
    memory_per_node_mib: int
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    last_sync_at: str | None = None


class TrainingJobDetail(TrainingJobListItem):
    description: str | None = None
    k8s_namespace: str
    k8s_job_name: str
    image: str
    command: str | list[str]
    last_condition_message: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    clean_pod_policy: CleanPodPolicy = "All"  # 结束清全部 Pod (与前端 runPolicy 默认对齐)
    ttl_seconds_after_finished: int = -1
    active_deadline_seconds: int | None = None
    job_max_retry_count: int = 0
    # 用户编辑的 runPolicy 裸 YAML 整段 (克隆原样回填; None=没编辑, 前端用 4 字段重建)
    run_policy_override: dict[str, Any] | None = None
    # 训练参数 (UI 详情"运行配置"卡渲)
    instance_type: str | None = None # 选的机型 (nodeSelector 锁定的池)
    env_secrets: list[EnvSecret] = Field(default_factory=list) # secret 注入的 env (克隆回填)
    code: CodeSource | None = None
    fsx_pvc: str | None = None
    fsx_gid: int | None = None
    fsx_mount_path: str | None = None
    s3_datasets: list[S3DatasetMount] = Field(default_factory=list)
    # 额外 FSx 挂载 (跨 ws 共享盘, 详情页展示) — create 已存 md, detail 漏读, 补
    extra_fsx_mounts: list[ExtraFsxMount] = Field(default_factory=list)
    experiment_id: str | None = None
    priority_class: str | None = None
    # 额外节点 (展示) · 存量任务无此字段 → None, 前端不显示
    spares: int | None = None
    # 拓扑调度 (展示)
    topology_mode: str | None = None
    topology_label: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    pods: list[dict[str, Any]] = Field(default_factory=list)


class TopologyLevel(BaseModel):
    """某机型可用的一个拓扑层级, 列表由细到粗 (层号越大越靠近实例)。"""

    # TAS 注解的 value 直接用它
    node_label: str
    # Topology.levels 里的声明位置 (1-based, 粗→细)
    depth: int
    # 后端给显示名 (前端不硬编映射); 未知 label 则同 node_label
    display_name: str
