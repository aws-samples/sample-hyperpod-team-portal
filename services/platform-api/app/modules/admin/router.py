"""Admin endpoints — DDB AuditLog 直读.

Endpoints:
- GET /admin/audit-logs — 全平台 audit; 按 query 参数分流:
  `?actor_user_id=` 走 actor-index GSI, `?scope=` 按 scope_key 查, 都不给则只列 global。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.repositories import audit_log

admin_router = APIRouter(tags=["admin"])


@admin_router.get(
    "/audit-logs",
    summary="查询审计日志",
    description=(
        "读 DDB `AuditLog` 表 (直读, 无 informer 中转), 供平台管理页 **审计** 面板使用.\n\n"
        "查询优先级 (取第一个命中的):\n"
        "1. `actor_user_id` → 走 `actor-index` GSI 只列该操作人的日志\n"
        "2. `scope` (e.g. `ws#<uuid>` / `cluster#<uuid>` / `global`) → 按 scope 列日志\n"
        "3. 都不给 → M1 只列 `scope=global` 的日志 (未做全表 scan; 后续加全局 GSI 再放开)\n\n"
        "结果按时间倒序, 上限 `limit` (默认 100, 最大 500).\n\n"
        "**权限**: 需平台超管 (超管闸门在挂载 admin_router 的上层 include 处配置)."
    ),
    responses={
        401: {"description": "未登录"},
        403: {"description": "非平台超管"},
    },
)
async def list_audit_logs(
    scope: str | None = Query(default=None, description="scope_key e.g. ws#<uuid> / cluster#<uuid> / global"),
    actor_user_id: str | None = Query(default=None, description="过滤特定操作人"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    if actor_user_id:
        items = await audit_log.list_by_actor(actor_user_id, limit=limit)
    elif scope:
        items = await audit_log.list_by_scope(scope, limit=limit)
    else:
        # M1: 全平台聚合先按 global scope 列, 不全表 scan (后续可加 GSI 全局)
        items = await audit_log.list_by_scope("global", limit=limit)
    return {"total": len(items), "items": items}
