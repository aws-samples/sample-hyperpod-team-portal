"""gpu_spec 拼装 + build_overview 聚合编排测试。"""
from unittest.mock import AsyncMock

import pytest

from app.modules.tasks import service
from app.modules.tasks.service import _to_row, format_gpu_spec
from app.repositories import resource_index as ri_repo


def test_format_gpu_spec_dev():
    assert service.format_gpu_spec("dev", {"gpu_count": 1}) == "1 GPU"


def test_format_gpu_spec_dev_cpu_only():
    assert service.format_gpu_spec("dev", {"gpu_count": 0}) == "CPU"


def test_format_gpu_spec_train():
    assert service.format_gpu_spec(
        "train", {"node_count": 2, "gpu_per_node": 8}
    ) == "16 GPU"


def test_format_gpu_spec_inference():
    assert service.format_gpu_spec(
        "inference", {"replicas": 2, "gpu_per_replica": 1}
    ) == "2 GPU"


def test_format_gpu_spec_dynamo():
    # 多机推理: node_count × gpu_per_worker (模板锁单节点规格)
    assert service.format_gpu_spec(
        "dynamo", {"node_count": 2, "gpu_per_worker": 8}
    ) == "16 GPU"


def test_format_gpu_spec_rayjob():
    # Ray 任务: worker_replicas × gpu_per_node + head_gpu (head 通常 0)
    assert service.format_gpu_spec(
        "rayjob", {"worker_replicas": 4, "gpu_per_node": 1, "head_gpu": 0}
    ) == "4 GPU"


def test_format_gpu_spec_rayjob_with_head_gpu():
    # head_gpu 计入总卡数
    assert service.format_gpu_spec(
        "rayjob", {"worker_replicas": 4, "gpu_per_node": 1, "head_gpu": 1}
    ) == "5 GPU"


def test_format_gpu_spec_missing_fields_is_cpu():
    # metadata 缺字段 → 当 0 → CPU (不抛)
    assert service.format_gpu_spec("train", {}) == "CPU"


def _item(rtype, rid, phase, *, created_at=None, started_at=None,
          desired_status=None, gpu_md=None, creator="alice", name="t",
          deleted_at=None, kueue_status=None, priority_class="p"):
    md = {"phase": phase, "started_at": started_at,
          "desired_status": desired_status, "priority_class": priority_class}
    # kueue_status 与 phase 同在 metadata 内 (informer 写)
    if kueue_status:
        md["kueue_status"] = kueue_status
    md.update(gpu_md or {})
    item = {
        "resource_type": rtype, "resource_id": rid,
        "creator_user_id": creator, "display_name": name,
        "created_at": created_at, "metadata": md,
    }
    # deleted_at 是 ResourceIndex item 顶层字段 (非 metadata 内), 参 crud._ri_to_dev
    if deleted_at is not None:
        item["deleted_at"] = deleted_at
    return item


@pytest.mark.asyncio
async def test_build_overview_maps_stats_and_sorts(monkeypatch):
    rows = [
        _item("train", "t1", "Running", created_at="2026-06-10T01:00:00Z",
              started_at="x", kueue_status="started",
              gpu_md={"node_count": 1, "gpu_per_node": 8}),
        _item("dev", "d1", "Creating", created_at="2026-06-10T03:00:00Z",
              kueue_status="queued", gpu_md={"gpu_count": 1}),
        _item("inference", "i1", "DeploymentInProgress",
              created_at="2026-06-10T02:00:00Z", kueue_status="queued",
              gpu_md={"replicas": 2, "gpu_per_replica": 1}),
    ]
    fake_repo = AsyncMock(return_value=rows)
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", fake_repo)

    result = await service.build_overview("ws-1")

    fake_repo.assert_awaited_once_with("ws-1", active_only=False)
    assert result["stats"] == {"running_starting": 1, "queued": 2}
    # 无 priority_values 传入 → priority_value 全 None (并列最低), 退化为
    # created_at 升序 (FIFO): t1(01:00) → i1(02:00) → d1(03:00)
    assert [t["id"] for t in result["tasks"]] == ["t1", "i1", "d1"]
    by_id = {t["id"]: t for t in result["tasks"]}
    assert by_id["t1"]["status"] == "Running"
    assert by_id["t1"]["kind"] == "train"
    assert by_id["t1"]["gpu_spec"] == "8 GPU"
    assert by_id["d1"]["status"] == "Creating"
    assert by_id["i1"]["status"] == "DeploymentInProgress"
    assert "raw_phase" not in by_id["t1"]
    assert by_id["t1"]["creator"] == "alice"


@pytest.mark.asyncio
async def test_build_overview_empty(monkeypatch):
    monkeypatch.setattr(
        service.ri_repo, "list_by_workspace", AsyncMock(return_value=[])
    )
    result = await service.build_overview("ws-empty")
    assert result == {
        "can_edit_priority": False,
        "stats": {"running_starting": 0, "queued": 0},
        "tasks": [],
    }


@pytest.mark.asyncio
async def test_build_overview_can_edit_for_superadmin(monkeypatch):
    monkeypatch.setattr(
        service.ri_repo, "list_by_workspace", AsyncMock(return_value=[])
    )
    result = await service.build_overview(
        "ws-1", current_user={"is_admin": True}
    )
    assert result["can_edit_priority"] is True


@pytest.mark.asyncio
async def test_build_overview_fills_priority_value(monkeypatch):
    rows = [
        _item("dev", "d1", "Creating", created_at="2026-06-10T03:00:00Z",
              gpu_md={"gpu_count": 1}),
    ]
    # _item 默认 priority_class="p"
    monkeypatch.setattr(
        service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows)
    )
    result = await service.build_overview(
        "ws-1", priority_values={"p": 100}
    )
    assert result["tasks"][0]["priority_value"] == 100


@pytest.mark.asyncio
async def test_build_overview_priority_value_none_when_unknown(monkeypatch):
    rows = [
        _item("dev", "d1", "Creating", created_at="2026-06-10T03:00:00Z",
              gpu_md={"gpu_count": 1}),
    ]
    monkeypatch.setattr(
        service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows)
    )
    # 映射里没有 "p" → priority_value=None
    result = await service.build_overview("ws-1", priority_values={"other": 5})
    assert result["tasks"][0]["priority_value"] is None


@pytest.mark.asyncio
async def test_build_overview_sorts_by_priority_then_fifo(monkeypatch):
    # 优先级: high=100, low=10。验证 高→低, 同档内 created_at 升序 (FIFO),
    # None (未知 class) 排最后。
    rows = [
        _item("dev", "low_old", "Creating", priority_class="low",
              created_at="2026-06-10T01:00:00Z", gpu_md={"gpu_count": 1}),
        _item("dev", "high_new", "Creating", priority_class="high",
              created_at="2026-06-10T05:00:00Z", gpu_md={"gpu_count": 1}),
        _item("dev", "high_old", "Creating", priority_class="high",
              created_at="2026-06-10T02:00:00Z", gpu_md={"gpu_count": 1}),
        _item("dev", "no_pc", "Creating", priority_class="unknown",
              created_at="2026-06-10T00:00:00Z", gpu_md={"gpu_count": 1}),
    ]
    monkeypatch.setattr(
        service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows)
    )
    result = await service.build_overview(
        "ws-1", priority_values={"high": 100, "low": 10}
    )
    # high 档内 FIFO (high_old 02:00 先于 high_new 05:00) → low → None(unknown) 垫底
    assert [t["id"] for t in result["tasks"]] == [
        "high_old", "high_new", "low_old", "no_pc"
    ]


@pytest.mark.asyncio
async def test_stats_by_kind_running(monkeypatch):
    # stats 按 kueue_status: started -> running_starting; queued -> queued (跨 kind 统一)
    rows = [
        _item("train", "t1", "Running", created_at="2026-06-10T01:00:00Z",
              kueue_status="started"),
        _item("dev", "d1", "Available", created_at="2026-06-10T02:00:00Z",
              kueue_status="started"),
        _item("inference", "i1", "DeploymentComplete",
              created_at="2026-06-10T03:00:00Z", kueue_status="started"),
        _item("dev", "d2", "Creating", created_at="2026-06-10T04:00:00Z",
              kueue_status="queued"),
        _item("inference", "i2", "DeploymentInProgress",
              created_at="2026-06-10T05:00:00Z", kueue_status="queued"),
    ]
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows))
    result = await service.build_overview("ws-1")
    # started = t1 + d1 + i1 = 3; queued = d2 + i2 = 2
    assert result["stats"] == {"running_starting": 3, "queued": 2}


@pytest.mark.asyncio
async def test_stats_skips_deleted_at(monkeypatch):
    rows = [
        _item("dev", "d1", "Available", created_at="2026-06-10T02:00:00Z",
              kueue_status="started"),
        # 软删行 (stop_requested 豁免回来的): kueue_status=finished, 在 tasks 列表
        # 但 finished 不计入 stats (无需单独看 deleted_at)
        _item("dev", "d2", "Stopped", created_at="2026-06-10T01:00:00Z",
              kueue_status="finished", deleted_at="2026-06-10T03:00:00Z"),
    ]
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows))
    result = await service.build_overview("ws-1")
    # d2 finished → 不计入 stats; d1 started → running_starting
    assert result["stats"] == {"running_starting": 1, "queued": 0}
    # 但 d2 仍出现在 tasks 列表 (供查日志/克隆)
    assert {t["id"] for t in result["tasks"]} == {"d1", "d2"}


@pytest.mark.asyncio
async def test_stats_by_kueue_status(monkeypatch):
    rows = [
        _item("train", "t1", "Created/Running", kueue_status="started"),
        _item("dev", "d1", "Progressing", kueue_status="queued"),
        _item("inference", "i1", "DeploymentComplete", kueue_status="started"),
    ]
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows))
    result = await service.build_overview("ws-1")
    assert result["stats"] == {"running_starting": 2, "queued": 1}


@pytest.mark.asyncio
async def test_stats_six_states_with_legacy_compat(monkeypatch):
    # 六态分桶: QuotaReserved/Admitted/PodsReady -> running (已拿配额);
    #          Queued/Evicted -> queued (在等配额); Finished 不计。
    # 并验证存量旧值 started/queued 仍归对应桶。
    rows = [
        _item("train", "t1", "Running", kueue_status="PodsReady"),
        _item("dev", "d1", "Available", kueue_status="Admitted"),
        _item("dev", "d2", "Creating", kueue_status="QuotaReserved"),  # 已拿配额 -> running
        _item("inference", "i1", "DeploymentInProgress", kueue_status="Queued"),
        _item("train", "t2", "Running", kueue_status="Evicted"),       # 被抢占 -> queued
        _item("train", "t3", "Running", kueue_status="started"),  # 存量旧值 -> running
        _item("dev", "d3", "Creating", kueue_status="queued"),    # 存量旧值 -> queued
        _item("inference", "i2", "DeploymentComplete", kueue_status="Finished"),  # 不计
    ]
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows))
    result = await service.build_overview("ws-1")
    # running = PodsReady + Admitted + QuotaReserved + started = 4
    # queued  = Queued + Evicted + queued = 3
    # Finished 不计
    assert result["stats"] == {"running_starting": 4, "queued": 3}


@pytest.mark.asyncio
async def test_stats_uses_kueue_status_not_phase(monkeypatch):
    # 故意让 phase 与 kueue_status 分叉, 锁住 stats 走 kueue_status 而非旧 phase 逻辑:
    #   dev Available 旧逻辑算 running, 但 kueue_status=queued 新逻辑算 queued
    #   train Pending 旧逻辑算 queued, 但 kueue_status=started 新逻辑算 running_starting
    rows = [
        _item("dev", "d1", "Available", kueue_status="queued"),
        _item("dev", "d2", "Available", kueue_status="queued"),
        _item("train", "t1", "Pending", kueue_status="started"),
    ]
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", AsyncMock(return_value=rows))
    result = await service.build_overview("ws-1")
    # 新逻辑(kueue_status): started=1(t1), queued=2(d1,d2) → {1,2}
    # 旧逻辑(phase): dev Available=running×2 + train Pending=queued×1 → {2,1} (不同!)
    assert result["stats"] == {"running_starting": 1, "queued": 2}


@pytest.mark.asyncio
async def test_active_only_uses_gsi_and_filters_zombies(monkeypatch):
    # active_only=True 走 list_active_by_workspace; 推理/开发机 GSI 混入的 finished
    # 僵尸行被二次过滤; 但训练 Finished 行不滤 (Failed 占卡是合法活跃, active_ws 故意保留)。
    active_rows = [
        _item("dev", "d1", "Running", created_at="2026-06-10T01:00:00Z",
              kueue_status="started", gpu_md={"gpu_count": 1}),
        # 推理/开发机 Finished = 真僵尸 → 滤掉
        _item("dev", "zombie", "Stopped", created_at="2026-06-10T02:00:00Z",
              kueue_status="finished", gpu_md={"gpu_count": 1}),
        _item("inference", "inf-zombie", "DeploymentFailed",
              created_at="2026-06-10T03:00:00Z",
              kueue_status="Finished", gpu_md={"gpu_count": 1}),
        # 训练 Finished (Failed 占卡) → 不滤, 保留可见
        _item("train", "t-occupy", "Failed", created_at="2026-06-10T04:00:00Z",
              kueue_status="Finished", gpu_md={"node_count": 1, "gpu_per_node": 1}),
    ]
    gsi_mock = AsyncMock(return_value=active_rows)
    monkeypatch.setattr(service.ri_repo, "list_active_by_workspace", gsi_mock)
    main_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", main_mock)

    result = await service.build_overview("ws-1", active_only=True)

    gsi_mock.assert_awaited_once_with("ws-1")
    main_mock.assert_not_awaited()
    # d1 (活跃) + t-occupy (训练Finished占卡, 不滤); 推理/开发机 Finished 僵尸被滤
    ids = {t["id"] for t in result["tasks"]}
    assert ids == {"d1", "t-occupy"}
    assert "zombie" not in ids
    assert "inf-zombie" not in ids


@pytest.mark.asyncio
async def test_active_only_false_uses_main_table(monkeypatch):
    main_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(service.ri_repo, "list_by_workspace", main_mock)
    gsi_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(service.ri_repo, "list_active_by_workspace", gsi_mock)

    await service.build_overview("ws-1", active_only=False)

    main_mock.assert_awaited_once_with("ws-1", active_only=False)
    gsi_mock.assert_not_awaited()


def test_to_row_llmd_merges_worst_kueue_status():
    item = {
        "resource_id": "id1", "resource_type": "llmd", "display_name": "t1",
        "k8s_name": "t1", "creator_user_id": "u",
        "metadata": {
            "phase": "Progressing", "kueue_status": "Queued",
            "gateway_kueue_status": "Admitted",
            "gpu_per_pod": 1, "nodes_per_replica": 2, "replicas": 3,
        },
    }
    row = _to_row(item, {})
    assert row["kind"] == "llmd"
    assert row["kueue_status"] == "Queued"
    assert row["gpu_spec"] == "6 GPU"


def test_to_row_llmd_half_deleted_not_terminal():
    item = {
        "resource_id": "id2", "resource_type": "llmd", "display_name": "t2",
        "k8s_name": "t2", "creator_user_id": "u",
        "metadata": {
            "phase": "Stopped", "kueue_status": "Finished",
            "gateway_kueue_status": "Admitted",
            "gpu_per_pod": 1, "nodes_per_replica": 1, "replicas": 1,
        },
    }
    row = _to_row(item, {})
    assert row["kueue_status"] == "Admitted"


@pytest.mark.asyncio
async def test_build_overview_active_keeps_occupying_rayjob(monkeypatch):
    # active_only=True 走 list_active_by_workspace (稀疏 GSI)。
    # rayjob 终态 (kueue_status=Finished) 但 RayCluster 未删 → controller 保留 active_ws,
    # 读侧不能像推理/开发机那样按 is_terminal 滤掉 (否则 ttl 窗口占卡任务从总览消失)。
    rows = [
        _item("rayjob", "r1", "SUCCEEDED", created_at="2026-06-10T01:00:00Z",
              kueue_status="Finished", gpu_md={"worker_replicas": 4,
              "gpu_per_node": 1, "head_gpu": 0}),
        # 对照: 推理终态僵尸行应被滤掉 (无 occupying 概念)
        _item("inference", "i1", "Deleted", created_at="2026-06-10T02:00:00Z",
              kueue_status="Finished", gpu_md={"replicas": 1, "gpu_per_replica": 1}),
    ]
    monkeypatch.setattr(
        service.ri_repo, "list_active_by_workspace", AsyncMock(return_value=rows)
    )

    result = await service.build_overview("ws-1", active_only=True)

    ids = [t["id"] for t in result["tasks"]]
    assert "r1" in ids          # rayjob 占卡行保留
    assert "i1" not in ids      # 推理终态僵尸行滤掉


def test_to_row_non_llmd_unchanged():
    item = {
        "resource_id": "id3", "resource_type": "train", "display_name": "t3",
        "k8s_name": "t3", "creator_user_id": "u",
        "metadata": {"phase": "Running", "kueue_status": "Admitted",
                     "node_count": 2, "gpu_per_node": 4},
    }
    row = _to_row(item, {})
    assert row["kueue_status"] == "Admitted"
    assert row["gpu_spec"] == "8 GPU"


@pytest.mark.asyncio
async def test_build_overview_keeps_llmd_half_deleted(monkeypatch):
    # llmd 半删态: 原始 kueue_status=Finished 但 gateway_kueue_status=Admitted
    # → 有效状态非终态 → 不被 active_only 过滤 (泄漏可见)。
    items = [{
        "resource_id": "id1", "resource_type": "llmd", "display_name": "t1",
        "k8s_name": "t1", "creator_user_id": "u", "active_ws": "ws-1",
        "metadata": {"phase": "Stopped", "kueue_status": "Finished",
                     "gateway_kueue_status": "Admitted"},
    }]
    monkeypatch.setattr(ri_repo, "list_active_by_workspace", AsyncMock(return_value=items))
    monkeypatch.setattr(service, "is_ws_admin", AsyncMock(return_value=True))
    res = await service.build_overview("ws-1", active_only=True)
    assert len(res["tasks"]) == 1
    assert res["tasks"][0]["kueue_status"] == "Admitted"
