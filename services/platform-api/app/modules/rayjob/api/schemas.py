"""RayJob (KubeRay) Pydantic Schemas.

Ray 训练流水线 (与训练任务 UI 平级, 独立 CRD)。对齐训练/dynamo:
    - 模型/代码走授权 FSx 挂载 (后端反查 pvc), entrypoint 指 FSx 上 .sh
    - 资源锁单节点 (head/worker 同规格) × worker_replicas
    - 固定 replicas (弹性 autoscaling 第二批)

env 注入走 secretKeyRef (值不进 CR 明文)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.i18n import t


class RayEnvSecret(BaseModel):
    """从 Secret 注入一个 env: env 名 + 本人 Secret 的 key; secret_ref 后端补。"""

    name: str
    secret_key: str
    secret_ref: str = ""


class S3DatasetRef(BaseModel):
    """引用 workspace 已挂的 S3 数据集 (只传 mount_id, 后端查真值; 照训练)。"""

    mount_id: str = Field(min_length=1, max_length=128)


class S3DatasetMount(BaseModel):
    """S3 数据集挂载 (存储/展示形状, 后端反查填真值; 照训练)。"""

    bucket: str = Field(min_length=1, max_length=63)
    prefix: str = Field(default="", max_length=512)
    mount_path: str = Field(min_length=1, max_length=255)
    pvc_name: str = Field(default="", max_length=253)


class FsxMountRef(BaseModel):
    """引用该 user 被授权的 FSx (只传 pvc_name, 后端反查授权真值; 照训练)。"""

    pvc_name: str = Field(min_length=1, max_length=253)


class ExtraFsxMount(BaseModel):
    """FSx 挂载 (存储/展示形状, 后端反查授权后填真值; 照训练)。"""

    pvc_name: str = Field(min_length=1, max_length=253)
    mount_path: str = Field(min_length=1, max_length=255)
    read_only: bool = False
    gid: int | None = None


class RayJobCreate(BaseModel):
    """创建 Ray 训练任务 (RayJob)."""

    # name 由后端从 display_name 派生; 输入侧禁传 (传了 422)。仍作响应字段返回真名。
    name: str | None = None
    # display_name 须 DNS 合法 (name 纯拼接不清洗)。上限 36 = RAYJOB_NAME_MAX(47) - 1 - 10随机。
    display_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]{1,34}[a-z0-9]$",
        description=(
            "任务显示名, 同时作为 K8s 任务名前缀。小写字母开头, 3-36 字符, "
            "只含 a-z 0-9 '-', 结尾须字母或数字。中文说明请写 description。"
        ),
    )

    @field_validator("display_name", mode="before")
    @classmethod
    def _explain_display_name(cls, v: object) -> object:
        if isinstance(v, str):
            if not all("\x20" <= c <= "\x7e" for c in v):
                raise ValueError(t("core.display_name_ascii"))
            if not 3 <= len(v) <= 36:
                raise ValueError(
                    t("rayjob.display_name_length", actual=len(v))
                )
        return v

    @field_validator("name")
    @classmethod
    def _reject_client_supplied_name(cls, v: str | None) -> None:
        if v:
            raise ValueError(t("core.name_not_client_supplied"))
        return None

    description: str | None = None

    # head/worker 各自镜像: head 落 CPU node 用 CPU 镜像 (gpu 镜像在无驱动 CPU node
    # NVML 崩); worker 落 GPU node 用 gpu 镜像。
    head_image: str = Field(default="rayproject/ray:2.9.0", max_length=512)
    worker_image: str = Field(default="rayproject/ray:2.9.0-gpu", max_length=512)

    # 共享存储 (照训练: 多 FSx 全平等挂载 + S3 数据集, 后端反查授权真值)
    fsx_mounts: list[FsxMountRef] = Field(default_factory=list)
    s3_datasets: list[S3DatasetRef] = Field(default_factory=list)
    # 入口脚本 (某挂载盘上路径), entrypoint = bash <此>
    entry_script_path: str = Field(min_length=1, max_length=512)

    # 规模 (固定 worker 数; 弹性第二批)
    worker_replicas: int = Field(default=1, ge=1, le=64)

    # head 资源 (协调节点: 调度/GCS/dashboard, 建议 CPU 机型省 GPU)
    head_instance_type: str = Field(min_length=1, max_length=64)
    head_gpu: int = Field(default=0, ge=0, le=8)
    head_cpu_request_millicores: int = Field(default=2000, ge=500, le=128000)
    head_cpu_limit_millicores: int = Field(default=4000, ge=500, le=128000)
    head_memory_request_mib: int = Field(default=8192, ge=1024, le=1048576)
    head_memory_limit_mib: int = Field(default=16384, ge=1024, le=1048576)
    head_efa: int = Field(default=0, ge=0, le=32)

    # worker 资源 (计算节点: 吃 GPU 算)
    worker_instance_type: str = Field(min_length=1, max_length=64)
    gpu_per_node: int = Field(default=1, ge=0, le=8)
    cpu_request_millicores: int = Field(default=2000, ge=500, le=128000)
    cpu_limit_millicores: int = Field(default=4000, ge=500, le=128000)
    memory_request_mib: int = Field(default=8192, ge=1024, le=1048576)
    memory_limit_mib: int = Field(default=16384, ge=1024, le=1048576)
    efa_per_node: int = Field(default=0, ge=0, le=32)
    max_run_hours: int = Field(default=24, ge=1, le=720)

    # 运行策略 (Ray spec 顶层平铺, 非 PyTorchJob runPolicy 嵌套):
    # ttl 跑完 CR 保留秒数 (★KubeRay 要 ≥0, 不接受 -1; 默认 1h), backoff 重试次数
    ttl_seconds_after_finished: int = Field(default=3600, ge=0)
    backoff_limit: int = Field(default=0, ge=0, le=10)

    env: dict[str, str] = Field(default_factory=dict)
    env_secrets: list[RayEnvSecret] = Field(default_factory=list)
    # Ray 镜像默认非 root, FSx gid 挡 → root 跑通 (同 dynamo)
    run_as_root: bool = True
    labels: dict[str, str] = Field(default_factory=dict)


class RayJobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    creator_user_id: str
    creator_display_name: str
    name: str
    display_name: str
    phase: str  # jobDeploymentStatus 派生 (Go controller 第二批; 第一版靠 sync)
    kueue_status: str | None = None
    worker_replicas: int = 1
    worker_instance_type: str  # 列表显 worker (计算节点) 机型
    gpu_per_node: int = 1
    # 生命周期时刻 (controller 从 CR status.startTime/endTime 派生); 前端"运行时长"用它:
    # (ended_at ?? now) - started_at。未就绪 / 老任务为 None。
    started_at: str | None = None
    ended_at: str | None = None
    created_at: str
    last_sync_at: str | None = None


class RayJobDetail(RayJobListItem):
    workspace_display_name: str
    description: str | None = None
    k8s_namespace: str
    k8s_cr_name: str  # ★ pod 定位锚点 (= CR 名; pod label ray.io/cluster)
    head_image: str = ""
    worker_image: str = ""
    entry_script_path: str | None = None
    extra_fsx_mounts: list[ExtraFsxMount] = Field(default_factory=list)
    s3_datasets: list[S3DatasetMount] = Field(default_factory=list)
    # head 资源 (协调节点)
    head_instance_type: str = ""
    head_gpu: int = 0
    head_cpu_request_millicores: int = 0
    head_cpu_limit_millicores: int = 0
    head_memory_request_mib: int = 0
    head_memory_limit_mib: int = 0
    head_efa: int = 0
    # worker 资源 (计算节点; worker_instance_type/gpu_per_node 继承自 ListItem)
    cpu_request_millicores: int
    cpu_limit_millicores: int
    memory_request_mib: int
    memory_limit_mib: int
    efa_per_node: int = 0
    max_run_hours: int = 24
    ttl_seconds_after_finished: int = 3600
    backoff_limit: int = 0
    env: dict[str, str] = Field(default_factory=dict)
    env_secrets: list[RayEnvSecret] = Field(default_factory=list)
    run_as_root: bool = True
    labels: dict[str, str] = Field(default_factory=dict)
    last_condition_message: str | None = None
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    pods: list[dict[str, Any]] = Field(default_factory=list)
