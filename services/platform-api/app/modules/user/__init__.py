"""User 模块.

PR feat/no-users-table-username-as-id, 2026-05-20:
    - DDB Users 表已删
    - 模块缩水到只剩 /api/v1/users/me endpoint
    - 历史的 from app.modules.user import crud as user_crud / models 全部清理
      (workspace / training / devinstance 模块已改造, 不再反查 user 表)
    - persistence/ + crud.py + models.py + schemas.py 已删

设计:
    - api/router.py 提供 /me endpoint
    - api/schemas.py 只保留 UserResponse
    - 用户身份 / email / display_name 全从 token claim 派生 (security.get_current_user)
    - is_admin 标记从 PlatformAdmins 表查 (PK=IdC username)
"""
