"""Dynamo (DynamoGraphDeployment) Pydantic Schemas.

多机推理流水线 (与 IEC 单机多副本并列), 对齐推理服务:
    - 模型走授权 FSx/S3 挂载源 (后端反查 pvc, 照训练/推理), tp/ep/model-path 进启动脚本
    - 资源走资源模板 (锁单节点 gpu/cpu/mem/efa) × node_count
    - backendFramework: sglang (最小切片锁定)

最小切片不含: 监控 / 日志 / 排队页 / 终端 / ALB endpoint / gang / share。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.i18n import t

DynamoBackend = Literal["sglang"]
DynamoModelSourceType = Literal["fsx", "s3"]


class DynamoS3Source(BaseModel):
    """S3 模型源 · 挂载源反查出 bucket/region + 用户填相对路径。"""

    bucket_name: str = Field(min_length=1, max_length=63)
    region: str = Field(default="us-west-2", max_length=32)
    model_location: str = Field(min_length=1, max_length=512)
    prefetch_enabled: bool = True


class DynamoCreate(BaseModel):
    """创建多机推理服务请求 (DynamoGraphDeployment)."""

    name: str = Field(min_length=3, max_length=63)
    display_name: str = Field(min_length=1, max_length=128)
    description: str | None = None

    backend_framework: DynamoBackend = "sglang"
    image: str = Field(
        default="nvcr.io/nvidia/ai-dynamo/sglang-runtime:1.2.1-efa-amd64",
        max_length=512,
    )

    # 模型来源 (授权挂载源, 后端反查真值)
    model_source_type: DynamoModelSourceType
    # FSx: 选中授权挂载源的 pvc_name (后端反查 mount_path + gid, 不信前端)
    fsx_pvc_name: str | None = None
    s3: DynamoS3Source | None = None

    # 多机: 节点数 (multinode.nodeCount, 单实例跨几机 TP/EP); tp/ep/model-path 在启动脚本
    node_count: int = Field(default=1, ge=1, le=64)
    # 副本数 (worker.replicas, 几个独立 worker 实例数据并行); 总 pod = replicas × node_count
    replicas: int = Field(default=1, ge=1, le=256)
    # 启动脚本 (含 python3 -m dynamo.sglang --model-path ... --tp-size ... --ep-size ...)
    launch_script: str = Field(min_length=1, max_length=8192)

    # 资源 (来自资源模板, 锁单节点规格)
    instance_type: str = Field(min_length=1, max_length=64)
    gpu_per_worker: int = Field(default=1, ge=1, le=8)
    cpu_request_millicores: int = Field(default=4000, ge=500, le=128000)
    cpu_limit_millicores: int = Field(default=4000, ge=500, le=128000)
    memory_request_mib: int = Field(default=16384, ge=1024, le=1048576)
    memory_limit_mib: int = Field(default=16384, ge=1024, le=1048576)
    efa_per_worker: int = Field(default=0, ge=0, le=32)

    # FSx 权限 (dynamo 镜像 uid=1000 读不了 FSx → root 跑通; 生产改 gid)
    run_as_root: bool = True

    labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _model_source_consistency(self) -> DynamoCreate:
        if self.model_source_type == "fsx" and not self.fsx_pvc_name:
            raise ValueError(t("dynamo.model_source_fsx_required"))
        if self.model_source_type == "s3" and self.s3 is None:
            raise ValueError(t("dynamo.model_source_s3_required"))
        return self


class DynamoListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    creator_user_id: str
    creator_display_name: str
    name: str
    display_name: str
    backend_framework: str
    phase: str  # status.state: initializing/pending/successful/failed (Go controller 写)
    kueue_status: str | None = None
    node_count: int = 1
    replicas: int = 1
    instance_type: str
    gpu_per_worker: int = 1
    endpoint_url: str | None = None  # 最小切片留空; 后续 ALB 回读 (前置阻塞#1)
    created_at: str
    last_sync_at: str | None = None


class DynamoDetail(DynamoListItem):
    workspace_display_name: str  # 仅详情页"工作空间"栏用; 列表页不用故不放 ListItem (省 N 次 GetItem)
    description: str | None = None
    k8s_namespace: str
    k8s_cr_name: str  # ★ pod 定位锚点 (= CR 名)
    image: str
    model_source_type: str
    fsx_pvc_name: str | None = None
    fsx_mount_path: str | None = None
    s3: DynamoS3Source | None = None
    launch_script: str | None = None
    cpu_request_millicores: int
    cpu_limit_millicores: int
    memory_request_mib: int
    memory_limit_mib: int
    efa_per_worker: int = 0
    run_as_root: bool = True
    labels: dict[str, str] = Field(default_factory=dict)
    last_condition_message: str | None = None
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    pods: list[dict[str, Any]] = Field(default_factory=list)
