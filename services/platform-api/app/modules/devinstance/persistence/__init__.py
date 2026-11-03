"""persistence · DB 表模型 + CRUD (纯数据访问, 无业务规则).

只允许本模块内部 import. 跨模块请走 orchestration 层的入口.
"""

from __future__ import annotations

from .crud import (
    create,
    delete,
    get,
    get_by_ws_name,
    list_by_workspace,
    update,
)
from .models import DevInstance

__all__ = [
    "DevInstance",
    "create",
    "delete",
    "get",
    "get_by_ws_name",
    "list_by_workspace",
    "update",
]
