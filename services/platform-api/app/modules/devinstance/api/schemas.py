"""DevInstance Pydantic Schemas (DDB-only).

UUID → str (DDB key); datetime → str (ISO8601).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.i18n import t

# OpenSSH authorized_keys 单条公钥: <type> <base64>[ <comment>]。type 限已知算法白名单,
# base64 只含合法字符, comment 可选且不含控制字符/换行。argv 传参已杜绝注入, 这里再做
# 格式校验纯为 UX (早报错) + 防把明显的垃圾/私钥写进去。
# 分隔符/注释前空白用 [ \t] 而非 \s: \s 含 \n, 会让多行值 (含换行注入企图) 通过。
_SSH_PUBKEY_RE = re.compile(
    r"^(?:ssh-ed25519|ssh-rsa|ssh-dss|ecdsa-sha2-nistp(?:256|384|521)|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r"[ \t]+[A-Za-z0-9+/]+={0,3}(?:[ \t]+[^\x00-\x1f]+)?$"
)


# ===== 共享存储挂载 =====

class VolumeMount(BaseModel):
    # name 前端不传, 由后端 cr.py 根据 mount_path slug 自动生成
    # (DevInstanceDetail 出口可能含此字段, 老开发机持久化的 name 透传)
    name: str | None = Field(default=None, max_length=63)
    mount_path: str = Field(pattern=r"^/[^\s]+$", min_length=2, max_length=256)
    pvc_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,252}$")

    @field_validator("name")
    @classmethod
    def _reject_reserved(cls, v: str | None) -> str | None:
        if v == "workspace-storage":
            raise ValueError(t("devinstance.reserved_storage_name"))
        return v

    @field_validator("mount_path")
    @classmethod
    def _reject_primary_mount(cls, v: str) -> str:
        if v.rstrip("/") in ("/home/sagemaker-user", "/home/jovyan"):
            raise ValueError(t("devinstance.mount_path_primary"))
        return v


class DevInstanceCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,62}$", max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    template_name: Literal[
        "sagemaker-jupyter-template", "sagemaker-code-editor-template"
    ] = "sagemaker-jupyter-template"
    image: str | None = None
    cpu_request_millicores: int = Field(ge=100, le=192000, default=2000)
    memory_request_mib: int = Field(ge=8192, le=786432, default=8192)
    gpu_count: int = Field(ge=0, le=8, default=0)
    # EFA 网卡数 (vpc.amazonaws.com/efa)。来自所选资源模板的 resource.efa; 0=不下发。
    # 上限给足 (le=32): 真实可用量由节点机型 EFA 容量决定, 超了 Pod 自然 Pending。
    efa_count: int = Field(ge=0, le=32, default=0)
    # 上限给足 (le=1000): 真实边界由 WorkspaceTemplate.primaryStorage.maxSize 管控
    # (当前 500Gi), 前端按模板 min/max 限制输入。此处仅防明显越界。default 对齐模板。
    storage_size_gib: int = Field(ge=1, le=1000, default=100)
    env: dict[str, str] = Field(default_factory=dict)
    volume_mounts: list[VolumeMount] = Field(default_factory=list)
    # 可选: 锁机型 (∈ ws ComputeQuota 已分配机型); None=不锁, 由调度器分配。
    instance_type: str | None = Field(default=None)
    # 资源池 (派生概念): "cpu"/"gpu"。开发机选池 → 后端展开成该池所有机型填 CR。
    # 新前端只传 pool; instance_type 保留兼容老前端/克隆。
    pool: Literal["cpu", "gpu"] | None = Field(default=None)


class DevInstanceUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    env: dict[str, str] | None = None


class DevInstanceResize(BaseModel):
    """改规格入参: 只改资源 (CPU/内存/GPU/EFA) 与资源池, 不含存储/镜像。

    存储不可改 — 主存储用的 storage class 未开 allowVolumeExpansion, EBS 不能扩;
    改规格只 merge-patch spec.resources + spec.affinity, PVC 不动 → /home/sagemaker-user 保留。
    字段边界与 DevInstanceCreate 的资源字段对齐。
    """

    cpu_request_millicores: int = Field(ge=100, le=192000)
    memory_request_mib: int = Field(ge=8192, le=786432)
    gpu_count: int = Field(ge=0, le=8, default=0)
    efa_count: int = Field(ge=0, le=32, default=0)
    # 资源池 (cpu/gpu): 不可换池 — 传入必须等于当前池, 否则 400 (换池会与镜像家族错配,
    # 镜像不在 resize 范围内)。省略 (None) = 不动机型约束 (推荐)。保留字段仅为兼容同池传值。
    pool: Literal["cpu", "gpu"] | None = Field(default=None)
    # FSx/S3 挂载全量集: None = 不碰挂载 (保留现有, 向后兼容 agent 只改资源); 给出列表
    # (含 []) = 设为恰好这些挂载 (全量替换, [] 即清空)。语义同 pool: 缺省即"不动"。
    # 前端改规格弹窗始终发全量 (预填当前挂载), 保证所见即所得。
    volume_mounts: list[VolumeMount] | None = Field(default=None)


class DevInstanceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    creator_user_id: str
    creator_display_name: str
    name: str
    display_name: str
    # 带随机后缀的真正 k8s CR 名 (= k8s_workspace_name 列, 如 foo-a1b2c3d4e5)。
    # 开发机的 name 只是用户输入的干净名 (无后缀), 列表页"任务名"行需显示此完整 CR 名。
    k8s_workspace_name: str = ""
    template_name: str
    app_type: str
    phase: str
    kueue_status: str | None = None  # Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像, informer 写)
    cpu_request_millicores: int
    memory_request_mib: int
    gpu_count: int
    efa_count: int = 0
    storage_size_gib: int
    access_url: str | None = None
    created_at: str
    started_at: str | None = None
    last_sync_at: str | None = None


class DevInstanceDetail(DevInstanceListItem):
    description: str | None = None
    # 创建时选的锁定机型 (None=未选, 由调度器分配)。来自 metadata_json.instance_type。
    instance_type: str | None = None
    pool: str | None = None  # 资源池 (cpu/gpu), 开发机详情显示用; 老数据可能无
    k8s_namespace: str
    k8s_workspace_name: str
    image: str
    desired_status: str
    priority_class: str | None = None
    ssm_managed_id: str | None = Field(
        default=None,
        description="[遗留] SSM managed instance id; 平台已切 directSSH, 新开发机恒为 null",
    )
    ssm_init_status: Literal["pending", "registering", "done", "failed"] = Field(
        default="pending",
        description="[遗留] SSM 注册状态; directSSH 下不再推进, 新开发机停在 pending",
    )
    last_condition_message: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    volume_mounts: list[VolumeMount] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class AuthorizedKeyAdd(BaseModel):
    """把用户的 SSH 公钥写入开发机 ~/.ssh/authorized_keys。"""

    public_key: str = Field(min_length=1, max_length=8192)

    @field_validator("public_key")
    @classmethod
    def _validate_pubkey(cls, v: str) -> str:
        v = v.strip()
        if not _SSH_PUBKEY_RE.match(v):
            raise ValueError(t("devinstance.invalid_ssh_public_key"))
        return v


class AuthorizedKeyResult(BaseModel):
    ok: bool
    message: str


class AccessInfo(BaseModel):
    id: str
    phase: str
    # directSSH: 固定 DNS 名 (VPC 内私有 zone), 停启不变。为空 = 未开 directSSH
    # 或 pod 未就绪 (SSH Service 注解还没建)。
    ssh_hostname: str | None = Field(
        default=None,
        description="directSSH 固定 DNS 名 (<ws>.<ns>.<domain>), VPC 内可解析",
    )
    ssh_port: int = Field(default=22222, description="directSSH sshd 监听端口")
    ssh_user: str = Field(default="sagemaker-user", description="登录用户")
    ssh_command: str | None = Field(
        default=None,
        description="一行 ssh, 复制即进开发机 (需先在 code editor 里贴公钥)",
    )
    ssh_config_snippet: str | None = Field(
        default=None,
        description="VSCode Remote-SSH 用 ~/.ssh/config 片段 (固定 DNS, 无 ProxyCommand)",
    )
    # 过渡保留: 平台已切 directSSH, 不再产出这些 SSM 字段 (恒 None), 待前端切完删。
    ssm_managed_id: str | None = None
    ssm_command: str | None = None
    notes: list[str] = Field(default_factory=list)


class SharedPVCInfo(BaseModel):
    name: str
    storage_class: str | None = None
    capacity_gib: int | None = None
    access_modes: list[str] = Field(default_factory=list)
    phase: str
    storage_kind: str = "unknown"
    # 成员级权限挂载 (list_permitted_mounts) 填: pod 内挂载路径 + ro/rw + gid.
    # 走 list_shared_pvcs (列 ns 全部 PVC) 时为 None.
    mount_path: str | None = None
    access: str | None = None
    # subdir 的 POSIX gid (team 隔离) · 训练任务进 pod securityContext (写的文件 team 可读写).
    gid: int | None = None
    # 是否本 ws 主目录 (gid == ws.primary_gid, 即自己 team 的盘, 非 share 来的别 team 盘)。
    # list_permitted_mounts 把主目录排第一 + 标 True 供前端优先展示。
    is_primary: bool = False


class TemplateInfo(BaseModel):
    name: str
    display_name: str
    app_type: str
    default_image: str
    allowed_images: list[str]
    allow_custom_images: bool
    default_storage_size_gib: int
    min_storage_size_gib: int
    max_storage_size_gib: int
    default_cpu_millicores: int
    default_memory_mib: int
    description: str | None = None


# ===== 管理员: 自定义 WorkspaceTemplate (BYOI) =====

class TemplateCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,62}$", max_length=63)
    display_name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    app_type: Literal["jupyterlab", "code-editor"]
    default_image: str = Field(min_length=1)
    allowed_images: list[str] = Field(min_length=1, max_length=32)
    default_cpu_millicores: int = Field(ge=100, le=192000, default=1000)
    default_memory_mib: int = Field(ge=8192, le=786432, default=8192)
    # 与 add-on 模板同基线 (见 deploy/cluster-prereq.sh step_template): 管理员新建
    # 自定义模板未填存储时的兜底默认。default 100Gi / 范围 10-500Gi。
    min_storage_size_gib: int = Field(ge=1, le=1000, default=10)
    default_storage_size_gib: int = Field(ge=1, le=1000, default=100)
    max_storage_size_gib: int = Field(ge=1, le=1000, default=500)
    allow_secondary_storages: bool = True

    @model_validator(mode="after")
    def _default_in_allowed(self) -> "TemplateCreate":
        if self.allowed_images and self.default_image not in self.allowed_images:
            raise ValueError(t("devinstance.default_image_not_allowed"))
        return self


class TemplatePatchAllowedImages(BaseModel):
    allowed_images: list[str] = Field(min_length=1, max_length=32)
