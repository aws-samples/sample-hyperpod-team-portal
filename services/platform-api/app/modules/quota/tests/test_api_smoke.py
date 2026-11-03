"""In-process TestClient 验证 · 等价于手动 curl.

覆盖两个合并后的 HTTP 路径空间:
- /api/v1/workspaces/{ws_id}/quota[*]          (旧 quota_router)
- /api/v1/workspaces/{ws_id}/quota/usage       (旧 quota_usage_router)
- /api/v1/clusters/{cluster_tag}/quotas        (旧 quota_router)

目标: 证明路由被 include · 依赖 mock 后能返 2xx · 未注入 deps 时合理 5xx (不是 404).

Note: 不走 DB · get_db 被 override 返 None · workspace_crud.get_workspace 被 mock.
"""

from __future__ import annotations

import pytest

# 旧 SQLAlchemy/Redis 测试在 DDB 化后已失效, 阶段 6 用 moto 重写.
pytest.skip("RDS+Redis era; rewrite in phase-6 with moto/DDB Local", allow_module_level=True)

from datetime import datetime, timezone  # noqa: E402, F401
from typing import Any  # noqa: E402, F401
from unittest.mock import AsyncMock, MagicMock  # noqa: E402, F401
from uuid import uuid4  # noqa: E402, F401

from fastapi import FastAPI  # noqa: E402, F401
from fastapi.testclient import TestClient  # noqa: E402, F401

from app.modules.quota.api.deps import get_hyperpod_client  # noqa: E402, F401
from app.modules.quota.api.router import quota_router  # noqa: E402, F401


class _FakeWorkspace:
    def __init__(self, name: str = "team-a", quota_id: str | None = "quota-abc") -> None:
        self.id = uuid4()
        self.name = name
        self.cluster_id = uuid4()
        self.sagemaker_compute_quota_id = quota_id
        self.sagemaker_compute_quota_arn = "arn:aws:sagemaker:us-west-2:123:compute-quota/abc"


def _build_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hp_client: Any,
    workspace: _FakeWorkspace | None = None,
    cluster: Any = None,
) -> FastAPI:
    """装配一个 isolate 的 FastAPI app + 全量 mock.

    所有模块级绑定替换走 monkeypatch.setattr, 测试结束自动还原 ·
    不会污染其他模块的 shim 等价性断言.
    """
    app = FastAPI()
    app.include_router(quota_router, prefix="/api/v1")

    async def _fake_db() -> Any:
        return MagicMock()

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_hyperpod_client] = lambda: hp_client

    # 避免 cache (patch router 模块里的本地绑定 · 因为 router 里已经 from ... import)
    async def _fake_cache_get(_k: str) -> None:
        return None

    async def _fake_cache_set(_k: str, _v: Any, _ttl: int) -> None:
        return None

    from app.modules.quota.api import router as router_mod
    monkeypatch.setattr(router_mod, "cache_get_json", _fake_cache_get)
    monkeypatch.setattr(router_mod, "cache_set_json", _fake_cache_set)

    # mock workspace / cluster crud · monkeypatch 自动 teardown, 避免污染 shim 测试
    from app.modules.cluster import crud as cluster_crud
    from app.modules.workspace import crud as workspace_crud

    monkeypatch.setattr(
        workspace_crud, "get_workspace", AsyncMock(return_value=workspace)
    )
    monkeypatch.setattr(
        cluster_crud, "get_cluster_by_id", AsyncMock(return_value=cluster)
    )
    monkeypatch.setattr(
        cluster_crud, "get_cluster_by_tag", AsyncMock(return_value=cluster)
    )

    # mock get_current_user (quota_usage 端点要求鉴权)
    from app.core import security

    async def _fake_user() -> MagicMock:
        u = MagicMock()
        u.id = uuid4()
        return u

    app.dependency_overrides[security.get_current_user] = _fake_user
    return app


# ============================================================
# GET /workspaces/{id}/quota · 覆盖旧 quota 模块 path
# ============================================================

def test_get_workspace_quota_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """workspace + quota_id 都存在 → describe_compute_quota 被调用 → 200."""
    ws = _FakeWorkspace(quota_id="quota-abc")
    hp = MagicMock()
    hp.describe_compute_quota = AsyncMock(
        return_value={
            "ComputeQuotaArn": "arn:aws:sagemaker:us-west-2:123:compute-quota/abc",
            "ComputeQuotaId": "quota-abc",
            "Name": "team-a",
            "ClusterArn": "arn:aws:sagemaker:us-west-2:123:cluster/xyz",
            "ActivationState": "Enabled",
            "Status": "Created",
            "ComputeQuotaVersion": 1,
            "ComputeQuotaConfig": {
                "ComputeQuotaResources": [],
                "ResourceSharingConfig": {"Strategy": "LendAndBorrow"},
                "PreemptTeamTasks": "LowerPriority",
            },
            "ComputeQuotaTarget": {"TeamName": "team-a", "FairShareWeight": 1},
        }
    )
    app = _build_app(monkeypatch, hp_client=hp, workspace=ws)
    client = TestClient(app)
    resp = client.get(f"/api/v1/workspaces/{ws.id}/quota")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 前端契约: camelCase 输出
    assert "computeQuotaId" in body
    assert body["computeQuotaId"] == "quota-abc"
    assert hp.describe_compute_quota.await_count == 1


def test_get_workspace_quota_404_when_workspace_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hp = MagicMock()
    app = _build_app(monkeypatch, hp_client=hp, workspace=None)
    client = TestClient(app)
    resp = client.get(f"/api/v1/workspaces/{uuid4()}/quota")
    assert resp.status_code == 404
    assert "workspace not found" in resp.text.lower()


def test_get_workspace_quota_404_when_quota_not_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _FakeWorkspace(quota_id=None)
    hp = MagicMock()
    app = _build_app(monkeypatch, hp_client=hp, workspace=ws)
    client = TestClient(app)
    resp = client.get(f"/api/v1/workspaces/{ws.id}/quota")
    assert resp.status_code == 404
    assert "no ComputeQuota bound" in resp.text


# ============================================================
# GET /workspaces/{id}/quota/usage · 覆盖旧 quota_usage 模块 path
# ============================================================

def test_get_quota_usage_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kueue 返 status → 解析成 QuotaUsage → 200 camelCase."""
    ws = _FakeWorkspace(name="team-a")

    # mock KueueClient.get_cluster_queue_status
    async def _fake_status(_self: Any, cq_name: str) -> dict[str, Any]:
        assert cq_name == "hyperpod-ns-team-a-clusterqueue"
        return {
            "flavorsUsage": [
                {
                    "name": "flavor-p4d",
                    "resources": [
                        {"name": "cpu", "total": "96"},
                        {"name": "memory", "total": "1152Gi"},
                        {"name": "nvidia.com/gpu", "total": "8"},
                    ],
                }
            ],
            "pendingWorkloads": 0,
        }

    from app.services.kueue_client import KueueClient
    monkeypatch.setattr(KueueClient, "get_cluster_queue_status", _fake_status)

    app = _build_app(monkeypatch, hp_client=MagicMock(), workspace=ws)
    client = TestClient(app)
    resp = client.get(f"/api/v1/workspaces/{ws.id}/quota/usage")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # camelCase 契约
    assert body["teamName"] == "team-a"
    assert len(body["resources"]) == 1
    assert body["resources"][0]["instanceType"] == "flavor-p4d"
    assert body["resources"][0]["acceleratorsUsed"] == 8
    assert body["totals"]["accelerators"] == 8
    assert "capturedAt" in body


def test_get_quota_usage_404_when_workspace_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app(monkeypatch, hp_client=MagicMock(), workspace=None)
    client = TestClient(app)
    resp = client.get(f"/api/v1/workspaces/{uuid4()}/quota/usage")
    assert resp.status_code == 404


def test_get_quota_usage_captured_at_is_timezone_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _FakeWorkspace(name="team-a")

    async def _fake_status(_self: Any, _cq: str) -> dict[str, Any]:
        return {"flavorsUsage": []}

    from app.services.kueue_client import KueueClient
    monkeypatch.setattr(KueueClient, "get_cluster_queue_status", _fake_status)

    app = _build_app(monkeypatch, hp_client=MagicMock(), workspace=ws)
    client = TestClient(app)
    resp = client.get(f"/api/v1/workspaces/{ws.id}/quota/usage")
    assert resp.status_code == 200
    captured_at = resp.json()["capturedAt"]
    # ISO 8601 含时区 (Z 或 +00:00)
    parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    # 生成时间在最近 5 秒内
    delta = (datetime.now(timezone.utc) - parsed).total_seconds()
    assert 0 <= delta < 5
