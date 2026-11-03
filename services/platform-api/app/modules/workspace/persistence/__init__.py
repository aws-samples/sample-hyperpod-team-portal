"""Workspace persistence layer.

包含 ORM models 与 CRUD 函数。

- `models`  ── SQLAlchemy Declarative mapping (workspace / user_workspace_role)
- `crud`    ── 跨模块允许调用的数据访问 API

注意: workspace + user_workspace_role 表是
**全局允许直读**的例外, 但 UPDATE/DELETE 仍必须通过本层的 CRUD 函数。
"""
