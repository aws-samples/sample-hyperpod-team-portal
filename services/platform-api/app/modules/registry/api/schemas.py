"""镜像中心 schemas · 工作空间镜像注册 (引用模型)。

注册 = 记一条 "ECR 镜像 URI + 适用用途" 引用。任何 ws 成员可注册/删。
用途多选: dev(开发机) / training(训练) / inference(推理)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ImageUse = Literal["dev", "training", "inference"]


class RegisterImageBody(BaseModel):
    """注册一条镜像引用。前端从 ECR 列表选好 URI, 后端直接存 (不二次校验 ECR)。"""

    image_uri: str = Field(min_length=3, max_length=1024)
    display_name: str = Field(default="", max_length=128)
    uses: list[ImageUse] = Field(min_length=1)
    # 来源标记: ecr-private/ecr-public (从 ECR 注册) 或 built (在线构建产出)。
    source: Literal["ecr-private", "ecr-public", "built"] = "ecr-private"


class WorkspaceImageItem(BaseModel):
    id: str
    image_uri: str
    display_name: str
    uses: list[ImageUse]
    source: str
    creator_username: str
    created_at: str


# ---------- 在线构建 (CodeBuild) ----------

BuildComputeType = Literal[
    "BUILD_GENERAL1_SMALL",
    "BUILD_GENERAL1_MEDIUM",
    "BUILD_GENERAL1_LARGE",
    "BUILD_GENERAL1_2XLARGE",
]


class SubmitBuildBody(BaseModel):
    """提交 Dockerfile 构建。只传 Dockerfile 文本 (不支持 COPY 本地文件)。"""

    dockerfile: str = Field(min_length=1, max_length=65536)
    # 镜像名:tag, 期望形如 namespace/repo-name:v1。镜像名 (: 前) 即 ECR repo 名原文
    # (平台不再加前缀), 须符合 ECR repo 规范: 小写字母/数字开头, 段用单个 . _ - 分隔,
    # / 分路径, 不允许大写/连续分隔符/首尾分隔符。
    #   ✓ my-team/bert  team/model:v1  a/b/c    ✗ My-Img  a__b  /x  x/  a//b
    # tag (: 后) 走 docker tag 规范: 字母数字 + . _ - (可含大写)。
    target_tag: str = Field(
        min_length=3, max_length=200,
        pattern=r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*:[a-zA-Z0-9._-]+$",
    )
    uses: list[ImageUse] = Field(min_length=1)
    compute_type: BuildComputeType = "BUILD_GENERAL1_LARGE"
    # 构建超时 (分钟). 默认 120 (2h); CodeBuild 上限 480 (8h), 下限 5。
    timeout_minutes: int = Field(default=120, ge=5, le=480)


class ImageBuildItem(BaseModel):
    id: str
    status: str
    target_tag: str
    target_uri: str = ""
    uses: list[ImageUse]
    compute_type: str
    timeout_minutes: int = 120
    dockerfile: str = ""
    logs_url: str = ""
    codebuild_id: str = ""
    creator_username: str
    created_at: str
    updated_at: str = ""
