"""Repositories: DDB-backed data access layer.

5 个 Repository, 1:1 对应 5 张 DDB 表:
    - users.UserRepository           Users
    - workspaces.WorkspaceRepository Workspaces
    - workspace_members.MemberRepository  WorkspaceMembers
    - resource_index.ResourceIndexRepository  ResourceIndex (dev + train 联合索引)
    - audit_log.AuditLogRepository   AuditLog

签名风格刻意贴近原 SQLAlchemy crud (e.g. get_user / list_users), 让业务模块迁移
时只改 import 不改调用点. 详细映射
"""
