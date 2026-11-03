"""Auth · 持久层.

本模块无独占表. 鉴权态完全依赖:
    - Cognito (token / session)
    - user 表 (owner: modules/user, 例外: auth 允许写 cognito_sub 回填)
    - user_workspace_role 表 (owner: modules/workspace, 例外: auth 允许只读)

"""
