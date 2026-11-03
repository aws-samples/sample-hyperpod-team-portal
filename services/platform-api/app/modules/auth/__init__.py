"""Auth 模块 · 鉴权 (M1 占位, Cognito OIDC 集成放 Phase 3+).

当前 M1: ``app.core.security.get_current_user`` 硬编码返第一个 active User,
完全不走 token / session. 整个 auth 目录是骨架占位, 方便后续迭代时
有个"这块归属 auth"的明确位置.

资产导向布局 (Wave 2):
    - domain/       (占位 · 后续放 token 解析 / ABAC 决策)
    - orchestration/ (占位 · 后续放 login / refresh 流)
    - api/          (占位 · 后续放 /auth/login, /auth/callback 端点)
    - persistence/  (空 · 无表, 所有状态 Cognito-side)
    - response/     (占位)

Phase 3+ 落地路径:
    1. Cognito UserPool Plus plan 接上
    2. domain/token.py: JWT 校验 + iss/aud 约束
    3. orchestration/oidc.py: Authorization Code Flow 回调
    4. api/router.py: /api/v1/auth/callback, /auth/logout
    5. M3+: IdC SAML upstream
"""
