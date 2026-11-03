"""验证合并后 router 的 HTTP 路径 set 与旧两套完全一致 (防止路径意外丢失/变更).

这条测试不启动 FastAPI, 只内省 APIRouter.routes 的 path list, 确保:
- /workspaces/{ws_id}/quota                  所有 method (GET/POST/PATCH/DELETE)
- /workspaces/{ws_id}/quota/usage            GET

NOTE: /clusters/{cluster_tag}/quotas 不再由 quota_router 提供 — 它由 cluster
模块的 cluster_router 提供 (原 quota 模块同路径端点是死代码, 已删, 2026-06-14)。
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.modules.quota.api.router import quota_router


def _paths_with_methods() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in quota_router.routes:
        if isinstance(r, APIRoute):
            for m in r.methods or set():
                out.add((r.path, m))
    return out


EXPECTED: set[tuple[str, str]] = {
    ("/workspaces/{ws_id}/quota", "GET"),
    ("/workspaces/{ws_id}/quota", "POST"),
    ("/workspaces/{ws_id}/quota", "PATCH"),
    ("/workspaces/{ws_id}/quota", "DELETE"),
    ("/workspaces/{ws_id}/quota/usage", "GET"),
}


def test_all_expected_paths_present() -> None:
    actual = _paths_with_methods()
    missing = EXPECTED - actual
    assert not missing, f"合并后丢失路径: {sorted(missing)}"


def test_no_unexpected_paths() -> None:
    """合并后 router 不应冒出计划外端点."""
    actual = _paths_with_methods()
    extra = actual - EXPECTED
    assert not extra, f"合并后多出未登记路径: {sorted(extra)}"
