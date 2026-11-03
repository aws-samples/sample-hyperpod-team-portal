import asyncio

import pytest

from worker.informers.base import CRInformer


class _FakeInformer(CRInformer):
    group = "g.example.com"
    version = "v1"
    plural = "things"
    resource_type = "thing"
    resource_kind = "Thing"

    async def derive_status_md(self, cr):
        return {"phase": (cr.get("status") or {}).get("phase")}

    async def resolve_ids(self, cr):
        labels = (cr.get("metadata") or {}).get("labels") or {}
        rid = labels.get("rid")
        ws = labels.get("ws")
        return (rid, ws) if rid and ws else None


def test_subclass_exposes_coordinates():
    inf = _FakeInformer(context=None)
    assert inf.group == "g.example.com"
    assert inf.plural == "things"
    assert inf.resource_type == "thing"


@pytest.mark.asyncio
async def test_derive_status_md_and_resolve_ids():
    inf = _FakeInformer(context=None)
    cr = {"metadata": {"labels": {"rid": "r1", "ws": "w1"}}, "status": {"phase": "Running"}}
    assert await inf.resolve_ids(cr) == ("r1", "w1")
    assert (await inf.derive_status_md(cr))["phase"] == "Running"


def test_base_requires_overrides():
    """基类直接实例化缺抽象方法实现 → TypeError。"""
    with pytest.raises(TypeError):
        CRInformer(context=None)  # 抽象方法未实现


class _AsyncEvents:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _RecordingInformer(CRInformer):
    group = "g.example.com"
    version = "v1"
    plural = "things"
    resource_type = "thing"
    resource_kind = "Thing"

    async def derive_status_md(self, cr):
        return {"phase": (cr.get("status") or {}).get("phase")}

    async def resolve_ids(self, cr):
        labels = (cr.get("metadata") or {}).get("labels") or {}
        return (labels.get("rid"), labels.get("ws")) if labels.get("rid") else None


@pytest.mark.asyncio
async def test_safe_reconcile_isolates_poison(monkeypatch):
    inf = _RecordingInformer(context=None)

    async def boom(cr):
        raise ValueError("poison")

    monkeypatch.setattr(inf, "_reconcile", boom)
    await inf._safe_reconcile({"metadata": {"name": "bad"}})  # 不抛
    assert inf.get_error_count() == 1


@pytest.mark.asyncio
async def test_cold_start_writes_each_and_marks_hb(monkeypatch):
    from worker.heartbeat import Heartbeat

    inf = _RecordingInformer(context=None)
    written = []

    async def fake_write(cr):
        written.append((cr.get("metadata") or {}).get("name"))

    monkeypatch.setattr(inf, "_reconcile", fake_write)
    hb = Heartbeat()

    class FakeCO:
        async def list_cluster_custom_object(self, *a, **kw):
            assert not kw.get("watch")
            return {"metadata": {"resourceVersion": "100"},
                    "items": [{"metadata": {"name": "a"}}, {"metadata": {"name": "b"}}]}

    rv = await inf.run_one_cycle(FakeCO(), hb, None)
    assert rv == "100"
    assert written == ["a", "b"]
    assert hb.seconds_since_progress() < 1.0


# --- watch 测试用: 替换 base.k8s_watch.Watch, 让 .stream() 直接 yield 准备好的事件 ---
# (真实 Watch 内部要解析 HTTP stream, 难 mock; 这里只测基类的事件分发/rv推进/心跳/超时逻辑)
def _patch_watch(monkeypatch, events=None, hang=False, raise_exc=None):
    class _FakeWatch:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def stream(self, func, *args, **kwargs):
            # 记录 Watch.stream 收到的续传 rv (验证不 LIST、用 rv 续传)
            _FakeWatch.last_kwargs = kwargs
            if raise_exc is not None:
                raise raise_exc
            if hang:
                await asyncio.sleep(3600)
                return
            for ev in (events or []):
                yield ev

    _FakeWatch.last_kwargs = None
    monkeypatch.setattr("worker.informers.base.k8s_watch.Watch", lambda: _FakeWatch())
    return _FakeWatch


@pytest.mark.asyncio
async def test_watch_from_rv_no_list(monkeypatch):
    from worker.heartbeat import Heartbeat

    inf = _RecordingInformer(context=None)
    list_calls = {"n": 0}

    class FakeCO:
        async def list_cluster_custom_object(self, *a, **kw):
            list_calls["n"] += 1  # 冷启动 LIST 才会调到; watch 走 Watch().stream
            return {"metadata": {"resourceVersion": "100"}, "items": []}

    fw = _patch_watch(monkeypatch, events=[
        {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "200"}}},
    ])

    rv = await inf.run_one_cycle(FakeCO(), Heartbeat(), "150")
    assert list_calls["n"] == 0           # watch 续传不 LIST
    assert fw.last_kwargs.get("resource_version") == "150"  # 用传入 rv 续传
    assert rv == "200"                    # bookmark 推进 rv


@pytest.mark.asyncio
async def test_watch_dispatches_events(monkeypatch):
    from worker.heartbeat import Heartbeat

    inf = _RecordingInformer(context=None)
    reconciled, deleted = [], []

    async def fake_reconcile(cr):
        reconciled.append((cr.get("metadata") or {}).get("name"))

    async def fake_mark_deleted(cr):
        deleted.append((cr.get("metadata") or {}).get("name"))

    monkeypatch.setattr(inf, "_reconcile", fake_reconcile)
    monkeypatch.setattr(inf, "_mark_deleted", fake_mark_deleted)
    _patch_watch(monkeypatch, events=[
        {"type": "ADDED", "object": {"metadata": {"name": "x", "resourceVersion": "301"}}},
        {"type": "DELETED", "object": {"metadata": {"name": "y", "resourceVersion": "302"}}},
    ])

    class FakeCO:
        async def list_cluster_custom_object(self, *a, **kw):
            return {"metadata": {"resourceVersion": "300"}, "items": []}

    rv = await inf.run_one_cycle(FakeCO(), Heartbeat(), "300")
    assert reconciled == ["x"]
    assert deleted == ["y"]
    assert rv == "302"


@pytest.mark.asyncio
async def test_cycle_timeout_is_normal(monkeypatch):
    from worker.heartbeat import Heartbeat

    inf = _RecordingInformer(context=None)
    _patch_watch(monkeypatch, hang=True)

    class FakeCO:
        async def list_cluster_custom_object(self, *a, **kw):
            return {"metadata": {"resourceVersion": "300"}, "items": []}

    rv = await inf.run_one_cycle(FakeCO(), Heartbeat(), "300", cycle_timeout=0.05)
    assert rv == "300"


@pytest.mark.asyncio
async def test_external_cancel_not_swallowed(monkeypatch):
    from worker.heartbeat import Heartbeat

    inf = _RecordingInformer(context=None)
    _patch_watch(monkeypatch, raise_exc=asyncio.CancelledError())

    class FakeCO:
        async def list_cluster_custom_object(self, *a, **kw):
            return {"metadata": {"resourceVersion": "400"}, "items": []}

    with pytest.raises(asyncio.CancelledError):
        await inf.run_one_cycle(FakeCO(), Heartbeat(), "400", cycle_timeout=5.0)


@pytest.mark.asyncio
async def test_reconcile_calls_partial_update(monkeypatch):
    """_reconcile 调 update_status_if_changed; 行存在路径不建 stub。"""
    inf = _RecordingInformer(context=None)
    calls = {}

    async def fake_update(**kw):
        calls.update(kw)
        return "updated"

    async def fake_stub(**kw):
        calls["stub"] = True

    monkeypatch.setattr("worker.informers.base.ri_repo.update_status_if_changed", fake_update)
    monkeypatch.setattr("worker.informers.base.ri_repo.create_stub", fake_stub)
    cr = {"metadata": {"name": "x", "resourceVersion": "10",
                       "labels": {"rid": "r1", "ws": "w1"}}, "status": {"phase": "Running"}}
    await inf._reconcile(cr)
    assert calls["resource_id"] == "r1" and calls["workspace_id"] == "w1"
    assert "stub" not in calls


@pytest.mark.asyncio
async def test_reconcile_absent_creates_stub(monkeypatch):
    """行不存在 (absent) → 走 create_stub 兜底。"""
    inf = _RecordingInformer(context=None)
    stub_called = {}

    async def fake_update(**kw):
        return "absent"

    async def fake_stub(**kw):
        stub_called.update(kw)

    monkeypatch.setattr("worker.informers.base.ri_repo.update_status_if_changed", fake_update)
    monkeypatch.setattr("worker.informers.base.ri_repo.create_stub", fake_stub)
    cr = {"metadata": {"name": "x", "resourceVersion": "10",
                       "labels": {"rid": "r1", "ws": "w1"}}, "status": {"phase": "Pending"}}
    await inf._reconcile(cr)
    assert stub_called["resource_id"] == "r1"
