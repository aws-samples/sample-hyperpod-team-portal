"""Workspace HTTP response 视图构建层.

职责: 从 persistence 层拿原始 ORM + 跨模块辅助 (cluster / user) 拼出
Pydantic response schema · **不**做业务决策 · **不**抛 HTTPException。

调 persistence.crud / cluster_crud / user_crud 读取关联数据是合法的;
任何 mutation 必须回 orchestration 层。
"""

from app.modules.workspace.response.builders import (
    build_workspace_detail,
    list_members_flow,
)

__all__ = ["build_workspace_detail", "list_members_flow"]
