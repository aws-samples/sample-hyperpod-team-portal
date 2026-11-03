"""kueue_status 待补偿队列测试 (read-after-create 竞态修复)。

背景: CR 创建瞬间 watch 事件早于 Kueue Workload 创建 → derive 出 kueue_status=None
→ "保持 DDB 旧值" → CR 进稳态不再发事件 → None 永久冻结。
修复: _reconcile 派生出 ks=None (非终态查不到 Workload) 时入队; 后台 backfill 循环
周期重查; 补上 (派生出非 None) / CR 删除 / 超时 → 出队。
"""
import asyncio

import pytest

from worker.informers.base import CRInformer


class _BackfillInformer(CRInformer):
    """可控派生结果的 fake: _ks_by_call 控制每次 derive 返回的 kueue_status。"""

    group = "g.example.com"
    version = "v1"
    plural = "things"
    resource_type = "thing"
    resource_kind = "Thing"

    def __init__(self, context=None):
        super().__init__(context=context)
        # 每个 resource_id 一个 ks 序列, 逐次 pop (模拟"先查不到, 后查到")
        self._ks_seq: dict[str, list] = {}

    async def derive_status_md(self, cr):
        rid = (cr.get("metadata") or {}).get("labels", {}).get("rid")
        seq = self._ks_seq.get(rid) or [None]
        ks = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"phase": (cr.get("status") or {}).get("phase"), "kueue_status": ks}

    async def resolve_ids(self, cr):
        labels = (cr.get("metadata") or {}).get("labels") or {}
        return (labels.get("rid"), labels.get("ws")) if labels.get("rid") else None


def _cr(rid, ws="w1", rv="10", phase="Progressing"):
    return {
        "metadata": {"name": rid, "resourceVersion": rv,
                     "labels": {"rid": rid, "ws": ws}},
        "status": {"phase": phase},
    }


@pytest.fixture
def _stub_repo(monkeypatch):
    """让 _reconcile 的 DDB 写入变 no-op, 只观察 backfill 队列行为。"""
    async def fake_update(**kw):
        return "updated"

    async def fake_stub(**kw):
        return None

    async def fake_get(*a, **kw):
        return None

    async def fake_mark_deleted(*a, **kw):
        return None

    monkeypatch.setattr("worker.informers.base.ri_repo.update_status_if_changed", fake_update)
    monkeypatch.setattr("worker.informers.base.ri_repo.create_stub", fake_stub)
    monkeypatch.setattr("worker.informers.base.ri_repo.get_resource", fake_get)
    monkeypatch.setattr("worker.informers.base.ri_repo.mark_deleted", fake_mark_deleted)


@pytest.mark.asyncio
async def test_reconcile_ks_none_enqueues(_stub_repo):
    """派生出 ks=None (非终态查不到 Workload) → 入待补偿队列。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": [None]}
    await inf._reconcile(_cr("r1"))
    assert "r1" in inf._backfill
    assert inf.backfill_queue_size() == 1


@pytest.mark.asyncio
async def test_reconcile_ks_present_not_enqueued(_stub_repo):
    """派生出 ks 有值 → 不入队。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": ["Admitted"]}
    await inf._reconcile(_cr("r1"))
    assert "r1" not in inf._backfill


@pytest.mark.asyncio
async def test_reconcile_ks_present_dequeues(_stub_repo):
    """已在队列的行, 后续 reconcile 派生出值 → 出队 (被正常事件抢先补上)。"""
    inf = _BackfillInformer()
    # 第一次 None 入队, 第二次 Admitted 出队
    inf._ks_seq = {"r1": [None, "Admitted"]}
    await inf._reconcile(_cr("r1", rv="10"))
    assert "r1" in inf._backfill
    await inf._reconcile(_cr("r1", rv="11"))
    assert "r1" not in inf._backfill


@pytest.mark.asyncio
async def test_mark_deleted_dequeues(_stub_repo):
    """CR 删除 → 出队 (不再补一个已删的任务)。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": [None]}
    await inf._reconcile(_cr("r1"))
    assert "r1" in inf._backfill
    await inf._mark_deleted(_cr("r1"))
    assert "r1" not in inf._backfill


@pytest.mark.asyncio
async def test_backfill_once_补上后出队(_stub_repo):
    """backfill 跑一轮: 此时 Workload 有了 (派生出 Admitted) → 写入 + 出队。"""
    inf = _BackfillInformer()
    # 入队时 None; backfill 重查时返回 Admitted
    inf._ks_seq = {"r1": [None, "Admitted"]}
    await inf._reconcile(_cr("r1"))
    assert "r1" in inf._backfill
    entry = inf._backfill["r1"]
    # 到重查时刻 (未超放弃时限) → 重查派生出 Admitted → _reconcile 内部出队
    await inf._run_backfill_once(now=entry["next_at"] + 1)
    assert "r1" not in inf._backfill


@pytest.mark.asyncio
async def test_backfill_still_none_stays(_stub_repo):
    """backfill 重查仍 None (Workload 还没建好) → 留在队列, 等下轮 (未超放弃时限)。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": [None]}  # 永远 None
    await inf._reconcile(_cr("r1"))
    entry = inf._backfill["r1"]
    # 到了重查时刻 (>next_at) 但远未超放弃时限 (10min) → 重查仍 None → 留队
    await inf._run_backfill_once(now=entry["next_at"] + 1)
    assert "r1" in inf._backfill


@pytest.mark.asyncio
async def test_backfill_gives_up_after_deadline(_stub_repo):
    """超过补偿时限 (默认 10min) 仍补不上 → 放弃出队 (防死缠 + 泄漏)。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": [None]}  # 永远 None
    await inf._reconcile(_cr("r1"))
    entry = inf._backfill["r1"]
    # 模拟该 entry 已入队 11 分钟 (超过 10min 上限)
    await inf._run_backfill_once(now=entry["enqueued_at"] + 11 * 60)
    assert "r1" not in inf._backfill


@pytest.mark.asyncio
async def test_backfill_short_circuits_when_ddb_has_ks(monkeypatch, _stub_repo):
    """重查前发现 DDB 已有 ks (别处写了) → 出队, 不再查 Workload。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": [None]}
    await inf._reconcile(_cr("r1"))
    entry = inf._backfill["r1"]

    # DDB 此刻已被别处写上 ks
    async def fake_get(ws, rtype, rid):
        return {"metadata": {"kueue_status": "Admitted"}}

    reconcile_calls = {"n": 0}
    orig = inf._reconcile

    async def counting_reconcile(cr):
        reconcile_calls["n"] += 1
        await orig(cr)

    monkeypatch.setattr("worker.informers.base.ri_repo.get_resource", fake_get)
    monkeypatch.setattr(inf, "_reconcile", counting_reconcile)
    await inf._run_backfill_once(now=entry["next_at"] + 1)
    assert "r1" not in inf._backfill          # 短路出队
    assert reconcile_calls["n"] == 0          # 没走重查 (省了 Workload 查询)


@pytest.mark.asyncio
async def test_backfill_short_circuits_when_ddb_deleted(monkeypatch, _stub_repo):
    """重查前发现 DDB 行已软删 (deleted_at) → 出队 (DELETED 事件漏捕获的兜底)。"""
    inf = _BackfillInformer()
    inf._ks_seq = {"r1": [None]}
    await inf._reconcile(_cr("r1"))
    entry = inf._backfill["r1"]

    async def fake_get(ws, rtype, rid):
        return {"deleted_at": "2026-06-28T00:00:00Z", "metadata": {}}

    monkeypatch.setattr("worker.informers.base.ri_repo.get_resource", fake_get)
    await inf._run_backfill_once(now=entry["next_at"] + 1)
    assert "r1" not in inf._backfill


@pytest.mark.asyncio
async def test_run_cancels_backfill_task(monkeypatch, _stub_repo):
    """run() 被 cancel 时, 同实例 spawn 的 backfill task 也被 cancel (不泄漏)。"""
    inf = _BackfillInformer()

    # _run_watch_forever 替换成一个会被 cancel 的长 sleep, 以便观察 finally 清理
    async def fake_watch(hb):
        await asyncio.sleep(3600)

    monkeypatch.setattr(inf, "_run_watch_forever", fake_watch)

    run_task = asyncio.create_task(inf.run(None))
    await asyncio.sleep(0.05)  # 让 run() 跑起来, spawn 出 backfill task
    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task
    # backfill task 应已被 finally cancel — 给事件循环一拍收尾
    await asyncio.sleep(0.05)
    # 队列里再 reconcile 不会被一个已死的 backfill 干扰 (间接验证: 无悬挂 task 报错)
    assert inf.backfill_queue_size() == 0

