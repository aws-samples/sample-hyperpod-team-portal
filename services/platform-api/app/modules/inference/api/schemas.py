"""Inference Pydantic Schemas (DDB-only —).

阶段 1 (本 PR 范围):
    - 引擎: SGLang (锁定)
    - 模型源: FSx / S3 / HuggingFace Hub
    - Smart Routing: 4 策略
    - L2 KV Cache: 可开关 (Helm Redis backend)
    - 单 replica 默认, 多 replica 手填 (KEDA 自动扩缩后置)

"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.i18n import t

# ============= 枚举 =============

# 推理引擎 · 阶段 1 锁 SGLang
Framework = Literal["sglang"]

# 模型源
ModelSourceType = Literal["fsx", "s3", "huggingface"]

# Smart Routing 策略 (operator v3.x)
RoutingStrategy = Literal[
    "roundrobin",   # 默认: 轮询 (无 KV 复用)
    "prefixaware",  # hash(prompt 前缀) → 同 pod (RAG 同文档)
    "kvaware",      # 找 L2 KV cache 命中的 pod (长上下文复用最佳)
    "session",      # session-id sticky (多轮对话)
]

# L2 KV Cache 后端
L2CacheBackend = Literal["redis"]


# ============= 模型源子模型 =============

class ModelSourceFsx(BaseModel):
    """FSx 模型源 · 容器内挂 /opt/ml/model."""

    filesystem_id: str = Field(min_length=1, max_length=64)
    # model_location: 相对 mountName 指的 team subdir 的路径 (operator 挂载 = mountName/model_location).
    # 空 → operator 挂整个 mountName 层到 /opt/ml/model, 模型路径在启动脚本写 (单 FSx)。
    # 非空 → 当 subPath 挂模型子目录。mount_name 锁 team 层; '..' 可逃出 subdir 到别 team → 必须拒.
    model_location: str = Field(default="", max_length=512)
    # mount_name: 平台从授权 FSx 的 full_mount_name 填 (= lustre名/subdir), 锁 team 层子目录隔离.
    # 不传则 operator 挂 fs root (能看整盘别 team) → 隔离失效, 故平台应总是传.
    mount_name: str | None = None
    dns_name: str | None = None

    @field_validator("model_location")
    @classmethod
    def _no_path_escape(cls, v: str) -> str:
        # 防 '..' 逃出 mountName 锁定的 team subdir (如 model_location='../team-b/x').
        # 同时拒绝绝对路径 (operator 期望相对 subdir).
        norm = v.strip()
        if norm.startswith("/"):
            raise ValueError(t("inference.model_location_absolute"))
        parts = norm.replace("\\", "/").split("/")
        if ".." in parts:
            raise ValueError(t("inference.model_location_dotdot"))
        return norm


class ModelSourceS3(BaseModel):
    """S3 模型源 · operator prefetch 到本地."""

    bucket_name: str = Field(min_length=1, max_length=63)
    region: str = Field(default="us-west-2", max_length=32)
    model_location: str = Field(min_length=1, max_length=512)
    prefetch_enabled: bool = True


class ModelSourceHuggingFace(BaseModel):
    """HuggingFace Hub 模型源 · 开发期用, 生产建议 FSx."""

    model_id: str = Field(min_length=1, max_length=256)
    prefetch_enabled: bool = True


# ============= L2 KV Cache 配置 =============

class L2KvCacheConfig(BaseModel):
    """L2 KV Cache 跨 pod 共享 (RAG / 长上下文场景命中率高)."""

    enabled: bool = False
    backend: L2CacheBackend = "redis"
    # Redis endpoint (Helm in-cluster: redis-master.kvcache:6379, ElastiCache: 自填)
    redis_endpoint: str = Field(default="redis-master.kvcache:6379", max_length=255)


# ============= 创建请求 =============

class InferenceCreate(BaseModel):
    """创建推理服务请求."""

    # 后端从 display_name 派生, 传了 422.
    name: str | None = None
    # 上限 29 = INFERENCE_NAME_MAX(40) - 1 - 10 随机. 前端有同一条 pattern,
    # check-validation-sync.mjs 防漂移.
    display_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]{1,27}[a-z0-9]$",
        description=(
            "服务显示名, 同时作为 K8s 任务名前缀。小写字母开头, 3-29 字符, "
            "只含 a-z 0-9 '-', 结尾须字母或数字。中文说明请写 description。"
        ),
    )
    description: str | None = None

    # 引擎 + 模型
    framework: Framework = "sglang"
    model_source_type: ModelSourceType
    fsx: ModelSourceFsx | None = None
    s3: ModelSourceS3 | None = None
    huggingface: ModelSourceHuggingFace | None = None
    # 模型逻辑名 (CR spec.modelName): 前端不填, 后端用派生 name (见 create flow)
    model_name: str = Field(default="", max_length=64)
    # 改它时默认 args 的 --model-path 和未覆盖的 HF_HOME 跟随 (cr.py)
    model_mount_path: str = Field(default="/opt/ml/model", min_length=1, max_length=256)

    # 资源 (单 replica)
    instance_type: str = Field(min_length=1, max_length=64)  # 例 ml.g6.2xlarge
    gpu_per_replica: int = Field(default=1, ge=1, le=8)
    cpu_request_millicores: int = Field(default=4000, ge=500, le=64000)
    cpu_limit_millicores: int = Field(default=8000, ge=500, le=128000)
    memory_request_mib: int = Field(default=16384, ge=1024, le=524288)
    memory_limit_mib: int = Field(default=32768, ge=1024, le=1048576)
    replicas: int = Field(default=1, ge=1, le=256)

    # SGLang 启动参数 (context_length 已并入 args 框, 不再单独字段)
    sglang_extra_args: list[str] = Field(default_factory=list)
    # 完整 command / args override (UI 两框). 任一非空则覆盖默认拼装:
    #   sglang_command 空 → ["python3","-m","sglang.launch_server"]
    #   sglang_args 空 → _sglang_args() 默认拼装 (--model-path ... --context-length ...)
    sglang_command: list[str] = Field(default_factory=list)
    sglang_args: list[str] = Field(default_factory=list)
    # 单脚本启动:
    #   非空 → CR worker.command=["/bin/sh","-c"], args=[launch_script]。
    #   优先级高于 sglang_command/args。需含 --model-path /opt/ml/model。
    launch_script: str | None = Field(default=None, max_length=8192)
    # 自定义 image (默 lmsysorg/sglang:latest)
    image: str = Field(default="lmsysorg/sglang:latest", max_length=512)

    # 端点
    invocation_endpoint: str = Field(default="v1/chat/completions", max_length=255)
    container_port: int = Field(default=8000, ge=1, le=65535)

    # 高级路由 + L2
    routing_strategy: RoutingStrategy = "roundrobin"
    l2_kv_cache: L2KvCacheConfig = Field(default_factory=L2KvCacheConfig)

    # 监控自动开启 (operator 用 metrics.enabled=true → PodMonitor)
    metrics_enabled: bool = True

    # 公网 SageMaker endpoint: 默认关, 只建 ClusterIP/ALB (集群内/VPC内调用)。
    # 开 → 渲 endpointName → operator 建公网 endpoint (SigV4), 多占 1 SageMaker ENI/子网。
    public_endpoint: bool = False

    # 用户自定义 label: 实验归类, 裸 key, 后端 validate_user_labels 校验。
    labels: dict[str, str] = Field(default_factory=dict)

    # Kueue 优先级数值 (旧字段, 仅记录; 实际 CR 用 priority-class label = common-priority,
    # 三类任务统一 · 产品决策 2026-06-11)。改单任务优先级走"优先级管理"页。
    priority_value: int = Field(default=80, ge=0, le=1000)

    # 环境变量 (额外注入)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("display_name", mode="before")
    @classmethod
    def _explain_display_name(cls, v: object) -> object:
        """最常见的两种输错换个人话报错, 其余由 pattern 兜底。

        必须 before: pattern 不匹配会直接抛, after 阶段根本跑不到。
        """
        if isinstance(v, str):
            if not all("\x20" <= c <= "\x7e" for c in v):
                raise ValueError(t("core.display_name_ascii"))
            if not 3 <= len(v) <= 29:
                raise ValueError(
                    t("inference.display_name_length", actual=len(v))
                )
        return v

    @field_validator("name")
    @classmethod
    def _reject_client_supplied_name(cls, v: str | None) -> None:
        if v:
            raise ValueError(t("core.name_not_client_supplied"))
        return None

    @model_validator(mode="after")
    def _model_source_consistency(self) -> InferenceCreate:
        match self.model_source_type:
            case "fsx":
                if self.fsx is None:
                    raise ValueError(t("inference.model_source_fsx_required"))
            case "s3":
                if self.s3 is None:
                    raise ValueError(t("inference.model_source_s3_required"))
            case "huggingface":
                if self.huggingface is None:
                    raise ValueError(t("inference.model_source_huggingface_required"))
        if self.cpu_limit_millicores < self.cpu_request_millicores:
            raise ValueError("cpu_limit < cpu_request")
        if self.memory_limit_mib < self.memory_request_mib:
            raise ValueError("memory_limit < memory_request")
        return self


# ============= 列表 / 详情视图 =============

class InferenceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    creator_user_id: str
    creator_display_name: str
    name: str
    display_name: str
    framework: str
    model_name: str
    model_source_type: str
    phase: str  # Pending / Provisioning / Running / Failed / Deleting
    kueue_status: str | None = None  # Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像, informer 写)
    replicas: int
    gpu_per_replica: int = 1
    instance_type: str
    endpoint_url: str | None = None  # ALB DNS, operator 起来才有
    created_at: str
    # 停止时刻; 未停止 / 加这字段前建的老任务为 None (前端显示 "-")。
    ended_at: str | None = None
    last_sync_at: str | None = None


class InferenceDetail(InferenceListItem):
    workspace_display_name: str  # 仅详情页"工作空间"栏用; 列表页不用故不放 ListItem (省 N 次 GetItem)
    description: str | None = None
    k8s_namespace: str
    k8s_endpoint_name: str  # spec.endpointName
    model_mount_path: str = "/opt/ml/model"
    image: str
    invocation_endpoint: str
    container_port: int
    sglang_extra_args: list[str] = Field(default_factory=list)
    # 单脚本启动 (克隆/详情展示用; 老数据为 None)
    launch_script: str | None = None
    cpu_request_millicores: int
    cpu_limit_millicores: int
    memory_request_mib: int
    memory_limit_mib: int
    fsx: ModelSourceFsx | None = None
    s3: ModelSourceS3 | None = None
    huggingface: ModelSourceHuggingFace | None = None
    routing_strategy: str = "roundrobin"
    l2_kv_cache: L2KvCacheConfig = Field(default_factory=L2KvCacheConfig)
    metrics_enabled: bool = True
    public_endpoint: bool = False
    alb_dns: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    last_condition_message: str | None = None
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    pods: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Pod 列表, 每个 Pod 包含 workload_name (所属 pod 级 Kueue Workload 名, 供 kueue-detail-by-workload 查询)",
    )
