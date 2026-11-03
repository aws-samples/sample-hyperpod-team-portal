"""domain · 纯 CR 渲染 + 字段约束 (无 IO · 无 DB · 无 k8s client).

只依赖:
    - pydantic 做 input schema 验证
    - 自身常量和辅助函数

禁止 import:
    - app.adapters.*     (外部系统)
    - app.db.*           (DB)
    - persistence.*      (CRUD)
    - orchestration.*    (flow)
"""

from __future__ import annotations

from .cr import (
    render_connection_cr,
    render_template_cr,
    render_workspace_cr,
)
from .lifecycle_hook import (
    SEED_COMMAND,
    SEED_SCRIPT,
)
from .validators import (
    parse_cpu_millicores,
    parse_gib,
    parse_memory_mib,
    parse_pvc_capacity_gib,
)

__all__ = [
    "SEED_COMMAND",
    "SEED_SCRIPT",
    "parse_cpu_millicores",
    "parse_gib",
    "parse_memory_mib",
    "parse_pvc_capacity_gib",
    "render_connection_cr",
    "render_template_cr",
    "render_workspace_cr",
]
