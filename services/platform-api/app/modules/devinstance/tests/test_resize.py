"""resize_flow 单测 · mock crud/k8s/quota · 验证改规格只 patch resources/affinity.

断言:
    - 同池给出 pool 时: patch spec.resources (含 GPU/EFA) + spec.affinity, 不含 storage
    - pool=None 时: 只 patch resources, 不动 affinity (保留原机型约束)
    - DDB 业务字段 (cpu/mem/gpu/efa + metadata.pool) 同步落库
    - pool 下无可用机型 → 400
    - 跨池 (payload.pool != 当前池) → 400 (资源池不可改, 防镜像错配)
    - 非创建者且非 ws 管理员 → 403
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.devinstance.api.schemas import DevInstanceResize
from app.modules.devinstance.orchestration import resize as resize_mod
from app.modules.devinstance.orchestration.resize import resize_flow


def _row(creator: str = "alice") -> dict[str, Any]:
    return {
        "id": "dev-1",
        "workspace_id": "ws-1",
        "creator_user_id": creator,
        "k8s_namespace": "hyperpod-ns-team-a-nlp",
        "k8s_workspace_name": "my-dev-abc123",
        "cpu_request_millicores": 2000,
        "memory_request_mib": 8192,
        "gpu_count": 1,
        "efa_count": 0,
        "metadata_json": {"pool": "gpu"},
    }


def _payload(**overrides) -> DevInstanceResize:
    base = {
        "cpu_request_millicores": 4000,
        "memory_request_mib": 16384,
        "gpu_count": 2,
        "efa_count": 1,
        "pool": "gpu",
    }
    base.update(overrides)
    return DevInstanceResize(**base)


@pytest.fixture
def _mocks(monkeypatch):
    row = _row()
    monkeypatch.setattr(resize_mod.crud, "get", AsyncMock(return_value=row))
    update = AsyncMock(side_effect=lambda db, r: r)
    monkeypatch.setattr(resize_mod.crud, "update", update)
    monkeypatch.setattr(resize_mod, "audit_devinstance", AsyncMock())
    # 池机型展开 (import 在函数内, patch 到源模块)
    monkeypatch.setattr(
        "app.modules.quota.orchestration.workspace_quota."
        "list_workspace_pool_instance_types",
        AsyncMock(return_value=["ml.g6.12xlarge"]),
    )
    monkeypatch.setattr(
        resize_mod, "_resolve_cpu_instance_groups", AsyncMock(return_value=[])
    )
    k8s = MagicMock()
    k8s.patch_workspace = AsyncMock(return_value={})
    return row, update, k8s


@pytest.mark.asyncio
async def test_patch_resources_and_affinity_no_storage(_mocks):
    row, update, k8s = _mocks
    await resize_flow(None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "alice"})

    patch = k8s.patch_workspace.await_args.args[2]
    spec = patch["spec"]
    assert "storage" not in spec
    req = spec["resources"]["requests"]
    assert req["cpu"] == "4000m"
    assert req["memory"] == "16384Mi"
    assert req["nvidia.com/gpu"] == "2"
    assert req["vpc.amazonaws.com/efa"] == "1"
    # 换池 → 重算 affinity, 含机型锁
    itypes = spec["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"][0]["matchExpressions"]
    assert any(
        e["key"] == "node.kubernetes.io/instance-type"
        and e["values"] == ["ml.g6.12xlarge"]
        for e in itypes
    )


@pytest.mark.asyncio
async def test_non_creator_forbidden(_mocks):
    """改规格仅创建者本人 (creator=alice), 别人 → 403, 不下发 patch。"""
    _row_, _update, k8s = _mocks
    with pytest.raises(HTTPException) as exc:
        await resize_flow(
            None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "bob"}
        )
    assert exc.value.status_code == 403
    k8s.patch_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_superadmin_also_forbidden(_mocks):
    """比 stop/start/delete 严: 平台超管也不能改别人开发机规格。"""
    _row_, _update, k8s = _mocks
    with pytest.raises(HTTPException) as exc:
        await resize_flow(
            None, k8s, MagicMock(), "dev-1", _payload(),
            {"user_id": "root", "is_admin": True},
        )
    assert exc.value.status_code == 403
    k8s.patch_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_gpu_to_zero_gpu_nulls_extended_resources(_mocks):
    """同池内把 GPU/EFA 降到 0 (GPU 池选无 GPU 模板): 扩展资源显式下发 null,
    让 merge-patch 删除旧 gpu/efa key (不换池, pool 仍 gpu)。"""
    row, update, k8s = _mocks
    await resize_flow(
        None, k8s, MagicMock(), "dev-1",
        _payload(gpu_count=0, efa_count=0, pool="gpu"),
        {"user_id": "alice"},
    )
    req = k8s.patch_workspace.await_args.args[2]["spec"]["resources"]["requests"]
    lim = k8s.patch_workspace.await_args.args[2]["spec"]["resources"]["limits"]
    assert req["nvidia.com/gpu"] is None
    assert req["vpc.amazonaws.com/efa"] is None
    assert lim["nvidia.com/gpu"] is None
    assert lim["vpc.amazonaws.com/efa"] is None


@pytest.mark.asyncio
async def test_ddb_business_fields_synced(_mocks):
    row, update, k8s = _mocks
    await resize_flow(None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "alice"})

    assert row["cpu_request_millicores"] == 4000
    assert row["memory_request_mib"] == 16384
    assert row["gpu_count"] == 2
    assert row["efa_count"] == 1
    assert row["metadata_json"]["pool"] == "gpu"
    update.assert_awaited_once()


@pytest.mark.asyncio
async def test_pool_none_keeps_affinity(_mocks):
    row, update, k8s = _mocks
    await resize_flow(
        None, k8s, MagicMock(), "dev-1",
        _payload(pool=None, gpu_count=0, efa_count=0),
        {"user_id": "alice"},
    )
    spec = k8s.patch_workspace.await_args.args[2]["spec"]
    assert "affinity" not in spec
    assert "storage" not in spec
    # metadata.pool 未变
    assert row["metadata_json"]["pool"] == "gpu"


@pytest.mark.asyncio
async def test_empty_pool_types_400(monkeypatch, _mocks):
    row, update, k8s = _mocks
    monkeypatch.setattr(
        "app.modules.quota.orchestration.workspace_quota."
        "list_workspace_pool_instance_types",
        AsyncMock(return_value=[]),
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await resize_flow(
            None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "alice"}
        )
    assert exc.value.status_code == 400
    k8s.patch_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_pool_rejected_400(_mocks):
    """跨池 (当前 gpu, payload cpu) → 400, 不下发 patch。资源池不可改。"""
    row, update, k8s = _mocks

    with pytest.raises(HTTPException) as exc:
        await resize_flow(
            None, k8s, MagicMock(), "dev-1",
            _payload(gpu_count=0, efa_count=0, pool="cpu"),
            {"user_id": "alice"},
        )
    assert exc.value.status_code == 400
    k8s.patch_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_volume_mounts_none_skips_mount_patch(monkeypatch, _mocks):
    """payload 不带 volume_mounts (None) → 不碰挂载: patch 无 volumes/securityContext,
    也不去读 ws (向后兼容 agent 只改资源)。"""
    row, update, k8s = _mocks
    get_ws = AsyncMock()
    monkeypatch.setattr(resize_mod.ws_crud, "get_workspace", get_ws)
    await resize_flow(None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "alice"})
    spec = k8s.patch_workspace.await_args.args[2]["spec"]
    assert "volumes" not in spec
    assert "containerSecurityContext" not in spec
    assert "podSecurityContext" not in spec
    get_ws.assert_not_awaited()


@pytest.mark.asyncio
async def test_volume_mounts_replaces_and_syncs_ddb(monkeypatch, _mocks):
    """给出 volume_mounts → 全量替换 spec.volumes + 下发 gid, 并同步 DDB metadata。"""
    row, update, k8s = _mocks
    monkeypatch.setattr(
        resize_mod.ws_crud,
        "get_workspace",
        AsyncMock(return_value={
            "metadata_json": {
                "primary_gid": 5000,
                "s3_mounts": [{"mount_path": "/data", "pvc_name": "pvc-data"}],
            }
        }),
    )
    monkeypatch.setattr(
        "app.repositories.mount_permissions.list_by_user_in_ws",
        AsyncMock(return_value=[]),
    )
    k8s.pvc_exists = AsyncMock(return_value=True)
    await resize_flow(
        None, k8s, MagicMock(), "dev-1",
        _payload(volume_mounts=[{"mount_path": "/data", "pvc_name": "pvc-data"}]),
        {"user_id": "alice"},
    )
    spec = k8s.patch_workspace.await_args.args[2]["spec"]
    assert [v["mountPath"] for v in spec["volumes"]] == ["/data"]
    assert spec["containerSecurityContext"]["runAsGroup"] == 5000
    assert spec["podSecurityContext"]["fsGroup"] == 5000
    assert row["metadata_json"]["volume_mounts"] == [
        {"name": None, "mount_path": "/data", "pvc_name": "pvc-data"}
    ]


@pytest.mark.asyncio
async def test_volume_mounts_empty_clears(monkeypatch, _mocks):
    """volume_mounts=[] → 清空: volumes 空表, securityContext 显式 null (ws 无 primary_gid)。"""
    row, update, k8s = _mocks
    monkeypatch.setattr(
        resize_mod.ws_crud,
        "get_workspace",
        AsyncMock(return_value={"metadata_json": {}}),
    )
    monkeypatch.setattr(
        "app.repositories.mount_permissions.list_by_user_in_ws",
        AsyncMock(return_value=[]),
    )
    await resize_flow(
        None, k8s, MagicMock(), "dev-1",
        _payload(volume_mounts=[]),
        {"user_id": "alice"},
    )
    spec = k8s.patch_workspace.await_args.args[2]["spec"]
    assert spec["volumes"] == []
    assert spec["containerSecurityContext"] is None
    assert spec["podSecurityContext"] is None
    assert row["metadata_json"]["volume_mounts"] == []


@pytest.mark.asyncio
async def test_volume_mounts_unpermitted_400(monkeypatch, _mocks):
    """勾选未授权的 mount_path → 400, 不下发 patch。"""
    row, update, k8s = _mocks
    monkeypatch.setattr(
        resize_mod.ws_crud,
        "get_workspace",
        AsyncMock(return_value={"metadata_json": {}}),
    )
    monkeypatch.setattr(
        "app.repositories.mount_permissions.list_by_user_in_ws",
        AsyncMock(return_value=[]),
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await resize_flow(
            None, k8s, MagicMock(), "dev-1",
            _payload(volume_mounts=[{"mount_path": "/nope", "pvc_name": "pvc-x"}]),
            {"user_id": "alice"},
        )
    assert exc.value.status_code == 400
    k8s.patch_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_schedules_rebuild(monkeypatch, _mocks):
    """运行中改规格 → 后台触发 stop→start 重建 (operator 不自动滚 Deployment)。"""
    row, update, k8s = _mocks
    row["desired_status"] = "Running"
    called: list[Any] = []
    monkeypatch.setattr(
        resize_mod, "_schedule_rebuild", lambda k, r: called.append(r)
    )
    await resize_flow(None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "alice"})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_stopped_no_rebuild(monkeypatch, _mocks):
    """停机态改规格 → 不重建 (下次 start 自然读新 spec)。"""
    row, update, k8s = _mocks
    row["desired_status"] = "Stopped"
    called: list[Any] = []
    monkeypatch.setattr(
        resize_mod, "_schedule_rebuild", lambda k, r: called.append(r)
    )
    await resize_flow(None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "alice"})
    assert called == []


@pytest.mark.asyncio
async def test_rebuild_stop_then_start():
    """_rebuild_for_resize: 先 patch Stopped, 等 Stopped==True, 再 patch Running。"""
    k8s = MagicMock()
    k8s.patch_workspace = AsyncMock(return_value={})
    k8s.get_workspace = AsyncMock(
        return_value={"status": {"conditions": [{"type": "Stopped", "status": "True"}]}}
    )
    await resize_mod._rebuild_for_resize(
        k8s, {"id": "dev-1", "k8s_namespace": "ns", "k8s_workspace_name": "w"}
    )
    desired = [
        c.args[2]["spec"]["desiredStatus"]
        for c in k8s.patch_workspace.await_args_list
    ]
    assert desired == ["Stopped", "Running"]


@pytest.mark.asyncio
async def test_non_creator_non_admin_403(monkeypatch, _mocks):
    row, update, k8s = _mocks
    monkeypatch.setattr(
        "app.core.security.is_ws_admin", AsyncMock(return_value=False)
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await resize_flow(
            None, k8s, MagicMock(), "dev-1", _payload(), {"user_id": "bob"}
        )
    assert exc.value.status_code == 403
    k8s.patch_workspace.assert_not_awaited()
