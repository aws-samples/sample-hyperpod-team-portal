"""Auth · HTTP 层 (Phase 3+ 落地).

规划端点:
    - GET  /api/v1/auth/login          # 302 -> Cognito authorize
    - GET  /api/v1/auth/callback       # Cognito -> 本服务回调
    - POST /api/v1/auth/logout
    - POST /api/v1/auth/refresh

M1 阶段 ``app.core.security.get_current_user`` 硬编码, 本目录暂不注册路由.
"""
