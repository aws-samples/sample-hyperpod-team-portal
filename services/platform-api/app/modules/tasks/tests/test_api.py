"""端点 smoke: 路由被 include + 鉴权 override 后返 200 + 结构正确。"""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import security
from app.core.security import get_current_user
from app.modules.tasks import service
from app.modules.tasks.api.router import get_priority_class_values, tasks_router


@pytest.fixture(autouse=True)
def _stub_membership(monkeypatch):
    # alice 是 ws 管理员 (role=admin): 任务总览仅 ws admin / 超管可看
    # (2026-06-15 收紧为 assert_ws_admin)。同时 can_edit_priority=True。
    monkeypatch.setattr(
        security, "_get_membership", AsyncMock(return_value={"role": "admin"})
    )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice"}
    # K8s WPC 映射 override: 测试不连真集群
    app.dependency_overrides[get_priority_class_values] = lambda: {}
    return app


def test_get_overview_200(monkeypatch):
    # stats 按 kueue_status 三态统计 (informer 写); started -> running_starting
    rows = [
        {
            "resource_type": "dev", "resource_id": "d1",
            "creator_user_id": "alice", "display_name": "bob-dev",
            "created_at": "2026-06-10T00:00:00Z",
            "metadata": {"phase": "Available", "gpu_count": 1,
                         "kueue_status": "started"},
        }
    ]
    # 总览恒 active_only=True → 走稀疏 GSI active-index
    monkeypatch.setattr(
        service.ri_repo, "list_active_by_workspace", AsyncMock(return_value=rows)
    )
    client = TestClient(_build_app())
    resp = client.get("/api/v1/workspaces/ws-1/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"] == {"running_starting": 1, "queued": 0}
    assert body["tasks"][0]["id"] == "d1"
    assert body["tasks"][0]["status"] == "Available"
    assert body["tasks"][0]["gpu_spec"] == "1 GPU"


def test_get_overview_empty_200(monkeypatch):
    monkeypatch.setattr(
        service.ri_repo, "list_active_by_workspace", AsyncMock(return_value=[])
    )
    client = TestClient(_build_app())
    resp = client.get("/api/v1/workspaces/ws-x/tasks")
    assert resp.status_code == 200
    assert resp.json() == {
        "can_edit_priority": True,
        "stats": {"running_starting": 0, "queued": 0},
        "tasks": [],
    }


def test_overview_always_active_only(monkeypatch):
    fake = AsyncMock(return_value=[])
    monkeypatch.setattr(service.ri_repo, "list_active_by_workspace", fake)
    client = TestClient(_build_app())

    client.get("/api/v1/workspaces/ws-1/tasks")
    # 总览恒 active_only=True (不再接受 query 参数) → 走稀疏 GSI active-index
    fake.assert_awaited_once_with("ws-1")


def test_non_member_forbidden_403(monkeypatch):
    # 非成员 (membership=None, 非超管) 看总览 → 403 (越权修复 2026-06-14)
    monkeypatch.setattr(security, "_get_membership", AsyncMock(return_value=None))
    client = TestClient(_build_app())
    resp = client.get("/api/v1/workspaces/ws-1/tasks")
    assert resp.status_code == 403


def test_overview_fills_priority_value(monkeypatch):
    rows = [
        {
            "resource_type": "dev", "resource_id": "d1",
            "creator_user_id": "alice", "display_name": "bob-dev",
            "created_at": "2026-06-10T00:00:00Z",
            "metadata": {"phase": "Pending", "gpu_count": 1,
                         "priority_class": "high"},
        }
    ]
    monkeypatch.setattr(
        service.ri_repo, "list_active_by_workspace", AsyncMock(return_value=rows)
    )
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice"}
    app.dependency_overrides[get_priority_class_values] = lambda: {"high": 1000}
    resp = TestClient(app).get("/api/v1/workspaces/ws-1/tasks")
    assert resp.status_code == 200
    assert resp.json()["tasks"][0]["priority_value"] == 1000
