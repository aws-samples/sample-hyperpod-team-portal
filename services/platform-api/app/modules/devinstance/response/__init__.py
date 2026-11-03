"""response · DTO 构建层 (ORM row → Pydantic schema).

只做字段映射 + 跨表 join 查询 (workspace / user 的 display_name).
不做业务规则, 不调 adapters.
"""

from __future__ import annotations

from .builders import build_access_info, build_detail, build_list_item

__all__ = [
    "build_access_info",
    "build_detail",
    "build_list_item",
]
