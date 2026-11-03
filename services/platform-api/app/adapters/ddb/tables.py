"""DDB 表名 + GSI 常量 (单一真实源).

 修订版 (PR feat/no-users-table-username-as-id, 2026-05-20):
    - 删 Users 表 (Cognito 是 user 数据源, DDB 不复制 user 主数据)
    - 业务表 user_id 改用 IdC username (管理员视角的标识, 加成员不依赖被加人登录)
    - 业务表写入时冗余 email + display_name (快照, 改名后陈旧但语义清晰)
    - Workspace 删 owner 概念 (你的需求: ws 由超管创建, 不记录创建人到主表)

5 张表:
    PlatformAdmins (username PK)
    Workspaces (workspace_id PK · 无 owner)
    WorkspaceMembers (workspace_id PK + username SK)
    ResourceIndex (workspace_id PK + resource_key SK · creator_username 冗余)
    AuditLog (scope_key PK + event_key SK · actor_username 冗余)
"""

from __future__ import annotations

from app.core.config import get_settings


def _full(name: str) -> str:
    return f"{get_settings().ddb_table_prefix}-{name}"


# ---------- PlatformAdmins ----------
# 平台超级管理员标记 · username PK (来自 IdC, 与 token identities[0].userId 一致)
# 旧版用 email PK, 改为 username 后任命时直接给 IdC username 即可.
PLATFORM_ADMINS_TABLE = _full("PlatformAdmins")

# ---------- Workspaces ----------
# 无 owner 概念, 删了 owner_user_id + owner-index GSI.
# 创建人审计放 AuditLog 表, 不进 ws 主表.
WORKSPACES_TABLE = _full("Workspaces")
WORKSPACES_GSI_QUOTA = "compute_quota_id-index"

# ---------- WorkspaceMembers ----------
# SK 改用 username (从老 user_id UUID 改造).
# 写入时冗余 email + display_name 快照.
WORKSPACE_MEMBERS_TABLE = _full("WorkspaceMembers")
WORKSPACE_MEMBERS_GSI_USER = "username-index"  # GSI 名也改

# ---------- ResourceIndex ----------
# creator_user_id 字段语义改 = IdC username
# 新增冗余: creator_email + creator_display_name (写入时快照)
RESOURCE_INDEX_TABLE = _full("ResourceIndex")
RESOURCE_INDEX_GSI_CREATOR = "creator-index"
RESOURCE_INDEX_GSI_TYPE_TIME = "type-time-index"
RESOURCE_INDEX_GSI_ACTIVE = "active-index" # 稀疏 GSI: PK=active_ws, SK=created_at
RESOURCE_INDEX_GSI_RESOURCE_ID = "resource_id-index"  # PK=resource_id: 按业务 id 精确取单行 (替代 _find_by_id 全扫)

# resource_type 取值 (SK 前缀 + GSI-2 PK)
RESOURCE_TYPE_DEV = "dev"
RESOURCE_TYPE_TRAIN = "train"
RESOURCE_TYPE_INFERENCE = "inference"
RESOURCE_TYPE_DYNAMO = "dynamo"
RESOURCE_TYPE_RAYJOB = "rayjob"
RESOURCE_TYPE_LLMD = "llmd"


def resource_key(resource_type: str, resource_id: str) -> str:
    """ResourceIndex SK 编码: '<type>#<id>'."""
    return f"{resource_type}#{resource_id}"


# ---------- AuditLog ----------
# actor_user_id 字段语义改 = IdC username
# 新增冗余: actor_email + actor_display_name
AUDIT_LOG_TABLE = _full("AuditLog")
AUDIT_LOG_GSI_ACTOR = "actor-index"

AUDIT_SCOPE_GLOBAL = "global"


# ---------- MountPermissions ----------
# 成员级 FSx 挂载授权: 哪个 member 能挂哪条挂载 + ro/rw.
# PK=workspace_id, SK="MOUNT#<mount_id>#USER#<username>"
# 删挂载: Query PK + begins_with(perm_key, "MOUNT#<mount_id>#") 一次捞全.
# 删成员/开发机创建查"我的权限": GSI username-index (PK=username, SK=workspace_id).
MOUNT_PERMISSIONS_TABLE = _full("MountPermissions")
MOUNT_PERMISSIONS_GSI_USER = "username-index"


def mount_perm_key(mount_id: str, username: str) -> str:
    """MountPermissions SK 编码: 'MOUNT#<mount_id>#USER#<username>'."""
    return f"MOUNT#{mount_id}#USER#{username}"


def mount_perm_prefix(mount_id: str) -> str:
    """某挂载所有授权记录的 SK 前缀 (begins_with 查询用)."""
    return f"MOUNT#{mount_id}#USER#"


# ---------- ResourceShares ----------
# 资源分享 (开发机/训练): creator 把资源分享给同 ws 指定成员。
# PK=workspace_id, SK="SHARE#<res_type>#<res_id>#USER#<target_username>"
# 列某资源被分享给谁: Query PK + begins_with(SK, "SHARE#<type>#<id>#USER#").
# 反查"分享给我的": GSI target-username-index (PK=target_username, SK=workspace_id).
RESOURCE_SHARES_TABLE = _full("ResourceShares")
RESOURCE_SHARES_GSI_USER = "target-username-index"


def share_key(res_type: str, res_id: str, username: str) -> str:
    """ResourceShares SK 编码: 'SHARE#<res_type>#<res_id>#USER#<username>'."""
    return f"SHARE#{res_type}#{res_id}#USER#{username}"


def share_prefix(res_type: str, res_id: str) -> str:
    """某资源所有分享记录的 SK 前缀 (begins_with 查询用)."""
    return f"SHARE#{res_type}#{res_id}#USER#"


# ---------- ApiTokens ----------
# 用户级 API Token (headless 到人). 每人一把: PK=username 天然唯一.
# 验证时按 token_hash 反查 → GSI token_hash-index.
# 明文只在创建响应返一次, 服务端只存 hash + 脱敏展示串.
API_TOKENS_TABLE = _full("ApiTokens")
API_TOKENS_GSI_HASH = "token_hash-index"


# ---------- ResourceTemplates ----------
# 资源模板 (开发机/训练/推理 统一一套, 不分类型).
# PK=workspace_id
# SK="tpl#<template_id>"   ← 全是 admin 管的统一档, 全 ws 可见 (无 type / 无 custom)
# 2026-06-14 确定: 三类共用一套模板, 仅 admin 管, 用户只能选不能改/自建.
RESOURCE_TEMPLATES_TABLE = _full("ResourceTemplates")

_RES_TPL_PREFIX = "tpl#"


def res_tpl_key(template_id: str) -> str:
    """ResourceTemplates SK: 'tpl#<template_id>' (统一档, 无 type/scope)."""
    return f"{_RES_TPL_PREFIX}{template_id}"


def res_tpl_prefix() -> str:
    """全部模板 SK 前缀 (begins_with 查询)。"""
    return _RES_TPL_PREFIX


# 工作空间镜像中心 (引用模型): 注册 = 记一条 "ECR 镜像 URI + 适用用途" 引用, 不复制镜像.
# PK=workspace_id
# SK="img#<image_id>"   ← 任何 ws 成员可注册/删 (镜像是共享资源), 全 ws 可见.
WORKSPACE_IMAGES_TABLE = _full("WorkspaceImages")

_WS_IMAGE_PREFIX = "img#"


def ws_image_key(image_id: str) -> str:
    """WorkspaceImages SK: 'img#<image_id>'."""
    return f"{_WS_IMAGE_PREFIX}{image_id}"


def ws_image_prefix() -> str:
    """全部镜像 SK 前缀 (begins_with 查询)。"""
    return _WS_IMAGE_PREFIX


# 镜像构建任务/历史 (CodeBuild): PK=workspace_id, SK="build#<build_id>".
# 与 WorkspaceImages 分表: build 是有状态流转的任务, image 是可用镜像资源.
IMAGE_BUILDS_TABLE = _full("ImageBuilds")

_IMAGE_BUILD_PREFIX = "build#"


def image_build_key(build_id: str) -> str:
    """ImageBuilds SK: 'build#<build_id>'."""
    return f"{_IMAGE_BUILD_PREFIX}{build_id}"


def image_build_prefix() -> str:
    """全部构建记录 SK 前缀 (begins_with 查询)。"""
    return _IMAGE_BUILD_PREFIX


def scope_key_workspace(workspace_id: str) -> str:
    return f"ws#{workspace_id}"


def scope_key_cluster(cluster_id: str) -> str:
    return f"cluster#{cluster_id}"


def event_key(created_at_iso: str, event_id: str) -> str:
    """AuditLog SK 编码: '<iso8601>#<event_id>'.

    ISO8601 字典序 == 时间序, Query ScanIndexForward=False 直接拿到时间倒序.
    """
    return f"{created_at_iso}#{event_id}"


# ---------- 全部表名（健康检查用）----------
ALL_TABLES: list[str] = [
    PLATFORM_ADMINS_TABLE,
    WORKSPACES_TABLE,
    WORKSPACE_MEMBERS_TABLE,
    RESOURCE_INDEX_TABLE,
    AUDIT_LOG_TABLE,
    MOUNT_PERMISSIONS_TABLE,
    RESOURCE_TEMPLATES_TABLE,
    API_TOKENS_TABLE,
    RESOURCE_SHARES_TABLE,
]
