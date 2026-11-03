"""llm-d Pydantic Schemas 分支B (LWS + sgl-model-gateway)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.i18n import t

# 模型源: fsx (授权 FSx 挂载源) + s3 (自建 mountpoint-s3 CSI PV/PVC), 都走 PVC (sglang 无感)
LlmdModelSourceType = Literal["fsx", "s3"]


class LlmdCreate(BaseModel):
    """创建 llm-d 多机推理服务请求 (一组 LWS + gateway 资源)."""

    # 后端从 display_name 派生, 传了 422。
    name: str | None = None
    # 上限 20 = LLMD_NAME_MAX(31) - 1 - 10 随机, 比训练/推理的 29 短 (见 core/naming.py)。
    # 前端有同一条 pattern, check-validation-sync.mjs 防漂移。
    display_name: str = Field(
        pattern=r"^[a-z][a-z0-9-]{1,18}[a-z0-9]$",
        description=(
            "服务显示名, 同时作为 K8s 任务名前缀。小写字母开头, 3-20 字符, "
            "只含 a-z 0-9 '-', 结尾须字母或数字。中文说明请写 description。"
        ),
    )
    description: str | None = None

    # fsx/s3 都不信前端: 后端反查授权 PVC / 自建 PV/PVC
    model_source_type: LlmdModelSourceType = "fsx"
    model_pvc: str | None = Field(default=None, max_length=253)
    s3_bucket: str | None = Field(default=None, max_length=63)
    s3_prefix: str | None = Field(default=None, max_length=512)
    launch_script: str = Field(min_length=1, max_length=8192)

    gpu_instance_type: str = Field(min_length=1, max_length=64)
    gateway_instance_type: str = Field(min_length=1, max_length=64)

    replicas: int = Field(default=1, ge=1, le=256)
    nodes_per_replica: int = Field(default=2, ge=2, le=64)
    gpu_per_pod: int = Field(default=1, ge=1, le=8)
    efa_per_pod: int = Field(default=0, ge=0, le=32)
    cpu_request_millicores: int = Field(default=4000, ge=500, le=128000)
    cpu_limit_millicores: int = Field(default=4000, ge=500, le=128000)
    memory_request_mib: int = Field(default=16384, ge=1024, le=1048576)
    memory_limit_mib: int = Field(default=16384, ge=1024, le=1048576)

    gateway_image: str = Field(
        default="lmsysorg/sgl-model-gateway:latest", max_length=512
    )
    sglang_image: str = Field(
        default="lmsysorg/sglang:v0.5.13.post1", max_length=512
    )
    gateway_replicas: int = Field(default=1, ge=1, le=16)
    gateway_extra_args: list[str] = Field(default_factory=list)
    gateway_cpu_request_millicores: int = Field(default=1000, ge=250, le=64000)
    gateway_cpu_limit_millicores: int = Field(default=4000, ge=250, le=64000)
    gateway_memory_request_mib: int = Field(default=2048, ge=512, le=262144)
    gateway_memory_limit_mib: int = Field(default=8192, ge=512, le=262144)

    # 建 internal ALB 暴露 endpoint (HTTP:80 明文, 无鉴权)。默认关: ~$20/月 + 占子网 IP。
    # 只在创建时生效, 事后改需重建。
    expose_alb: bool = False

    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("display_name", mode="before")
    @classmethod
    def _explain_display_name(cls, v: object) -> object:
        """最常见的两种输错换个人话报错, 其余由 pattern 兜底。

        必须 before: pattern 不匹配会直接抛, after 阶段根本跑不到。
        """
        if isinstance(v, str):
            if not all("\x20" <= c <= "\x7e" for c in v):
                raise ValueError(t("core.display_name_ascii"))
            if not 3 <= len(v) <= 20:
                raise ValueError(
                    t("llmd.display_name_length", actual=len(v))
                )
        return v

    @field_validator("name")
    @classmethod
    def _reject_client_supplied_name(cls, v: str | None) -> None:
        if v:
            raise ValueError(t("core.name_not_client_supplied"))
        return None

    @model_validator(mode="after")
    def _model_source_consistency(self) -> LlmdCreate:
        # 模型源仅决定挂载 (建 PV/挂 PVC 到 /model); 模型路径在 launch_script 里用户自己写。
        if self.model_source_type == "fsx" and not self.model_pvc:
            raise ValueError(t("llmd.model_source_fsx_required"))
        if self.model_source_type == "s3" and (not self.s3_bucket or not self.s3_prefix):
            raise ValueError(t("llmd.model_source_s3_required"))
        return self


class LlmdListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    creator_user_id: str
    creator_display_name: str
    name: str
    display_name: str
    phase: str  # initializing/pending/successful/failed (Go controller 写)
    kueue_status: str | None = None
    replicas: int = 1
    nodes_per_replica: int = 2
    gpu_instance_type: str
    gpu_per_pod: int = 1
    # http://<alb-dns>; ALB 就绪【且】gateway 有 Ready 副本才填 (见 orchestration/sync)
    endpoint_url: str | None = None
    created_at: str
    # 停止时刻; 未停止 / 加这字段前建的老任务为 None (前端显示 "-")。
    ended_at: str | None = None
    last_sync_at: str | None = None


class LlmdDetail(LlmdListItem):
    workspace_display_name: str  # 仅详情页"工作空间"栏用 (省列表页 N 次 GetItem)
    description: str | None = None
    k8s_namespace: str
    k8s_name: str  # CR base 名 (= name); gateway svc = <k8s_name>-gateway, LWS = <k8s_name>-multi
    model_source_type: str = "fsx"
    launch_script: str
    model_pvc: str
    s3_bucket: str | None = None
    s3_prefix: str | None = None
    gateway_instance_type: str = ""
    efa_per_pod: int = 0
    cpu_request_millicores: int = 4000
    cpu_limit_millicores: int = 4000
    memory_request_mib: int = 16384
    memory_limit_mib: int = 16384
    gateway_image: str
    sglang_image: str
    gateway_replicas: int = 1
    gateway_extra_args: list[str] = Field(default_factory=list)
    gateway_cpu_request_millicores: int = 1000
    gateway_cpu_limit_millicores: int = 4000
    gateway_memory_request_mib: int = 2048
    gateway_memory_limit_mib: int = 8192
    expose_alb: bool = False
    # ALB hostname, 一有地址就写 (供前端区分"ALB 就绪中"与"可调用")
    alb_dns: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    last_condition_message: str | None = None
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    pods: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Pod 列表 (gateway/leader/worker); 每项含 group (副本组序号字符串, gateway 为 None) + workload_name (所属 Kueue Workload 名, 供 kueue-detail 查询)",
    )
