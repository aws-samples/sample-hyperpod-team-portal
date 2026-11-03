"""User · 领域层.

当前无独立业务规则 (email 格式在 pydantic schema 里, uid/gid 分配在 DB default).
M2 接 Cognito 后, cognito_sub / identity_center_id 的校验 / 回填策略放这里.
目录保留占位以对齐 Wave 2 标准布局.
"""
