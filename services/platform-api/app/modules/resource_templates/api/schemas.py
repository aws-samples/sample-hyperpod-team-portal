"""资源模板 schemas (开发机/训练/推理 公用一表 + 统一字段, 单位: CPU 核 / 内存 GiB).

2026-06-14 确定: 三类共用一套模板, 推理也 req=lim 不区分。
统一字段 TemplateResource: gpu + cpu_cores + mem_gib (单值)。
推理选模板时, 单值同时填 create 的 cpu_request/limit 与 mem_request/limit (相等)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- 资源字段 (三类统一: 单值, K8s req=lim) ----------

class TemplateResource(BaseModel):
    """统一资源模板字段 (dev/train/inference 共用, 单值, K8s req=lim)。

    gpu 单节点物理上限 8 保留; cpu/mem 不设上限 (B300 等大机型单节点几百核 TB 内存,
    admin 建模板时按真实机型填, 真实边界由节点容量 + ComputeQuota 卡)。
    """

    gpu: int = Field(ge=0, le=8)
    cpu_cores: float = Field(gt=0)
    mem_gib: float = Field(gt=0)
    # EFA 网卡数 (多节点 GPU 训练高速 RDMA 网络)。默认 0 兼容老模板 (老数据无此字段
    # → 校验补 0); 创建 CR 时填 vpc.amazonaws.com/efa resource。
    efa: int = Field(default=0, ge=0)


# ---------- 请求体 ----------

class TemplateCreate(BaseModel):
    """建模板 (统一一套, 仅 ws admin)。无 type / scope: 三类共用同一套。"""

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    # 统一资源字段 (gpu/cpu_cores/mem_gib), orchestration 层用 TemplateResource 校验
    resource: dict = Field(default_factory=dict)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    resource: dict | None = None


# ---------- 响应 ----------

class TemplateItem(BaseModel):
    template_id: str
    name: str
    description: str | None = None
    resource: dict
    creator_username: str
    created_at: str
    updated_at: str
