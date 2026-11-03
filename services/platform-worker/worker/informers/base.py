"""CRInformer: 通用 K8s CR informer 骨架 (watch → reconcile → 写 DDB)。

通用逻辑 (阶段0训练加固验证过): asyncio.timeout 周期 + rv 续传不 LIST + bookmark +
401 token 刷新 + 410 回退冷启动 + per-CR 毒丸隔离 + 心跳。
子类填差异: group/version/plural、resource_type/resource_kind、derive_status_md、resolve_ids。
"""
from __future__ import annotations

import abc
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import watch as k8s_watch
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.exceptions import ApiException

from app.adapters.k8s.base import K8sClientBase, reset_config_cache
from app.repositories import resource_index as ri_repo

REQUEST_TIMEOUT_SECONDS = 300   # 客户端 watch 周期超时 (5min): asyncio.timeout 强制周期返回
SERVER_TIMEOUT_SECONDS = 3600   # 服务端 watch 超时: 次要兜底
_MAX_401_RETRIES = 3            # EKS token 过期常态; 连续刷 token 仍 401 超此数才判真权限问题
_COLD_START_SKIP_HOURS = 72     # 冷启动时跳过最后更新超过此小时数的 CR (DDB 必已是最新)

# ── kueue_status 待补偿队列 (read-after-create 竞态修复) ──
# CR 创建瞬间 watch 事件早于 Kueue Workload 创建 → derive ks=None ("保持旧值")
# → CR 进稳态不再发事件 → None 永久冻结。后台 backfill 循环周期重查补上。
_BACKFILL_SCAN_INTERVAL = 5      # backfill 循环扫描间隔 (秒)
_BACKFILL_RETRY_INTERVAL = 5     # 单个 entry 两次重查的最小间隔 (秒, 退避起点)
_BACKFILL_MAX_INTERVAL = 60      # 退避间隔上限 (秒)
_BACKFILL_GIVE_UP_SECONDS = 300  # 入队后持续补不上超此秒数 → 放弃 (5min, 防死缠+泄漏)


def should_retry_after_401(consecutive_401: int) -> bool:
    """401 后是否该重试 (刷 token 重连)。token 过期 (常态) → reload 即恢复, 应重试。"""
    return consecutive_401 <= _MAX_401_RETRIES


class CRInformer(K8sClientBase, abc.ABC):
    """通用 CR informer 骨架。子类必须设坐标属性 + 实现两个抽象方法。"""

    # --- 子类必须覆盖 (类属性) ---
    group: str = ""
    version: str = ""
    plural: str = ""
    resource_type: str = ""
    resource_kind: str = ""

    def __init__(self, context: str | None = None) -> None:
        super().__init__(context=context)
        self.log = logging.getLogger(f"worker.informer.{self.resource_type or 'cr'}")
        self._error_count = 0
        # 待补偿队列 (实例级, 每类 informer 各一份): resource_id → entry。
        # entry = {cr: CR快照, enqueued_at: 入队时刻, next_at: 下次重查时刻, interval: 当前退避间隔}
        self._backfill: dict[str, dict[str, Any]] = {}

    # --- 子类必须实现 ---
    @abc.abstractmethod
    async def derive_status_md(self, cr: dict[str, Any]) -> dict[str, Any]:
        """从 CR 推导要写 DDB 的状态字段 dict (phase 等)。"""

    @abc.abstractmethod
    async def resolve_ids(self, cr: dict[str, Any]) -> tuple[str, str] | None:
        """从 CR 拿 (resource_id, workspace_id)。无法解析返 None → 跳过。"""

    # --- 通用错误计数 (毒丸隔离用) ---
    def get_error_count(self) -> int:
        return self._error_count

    def reset_error_count(self) -> None:
        self._error_count = 0

    # --- 冷启动跳过判定 ---
    @staticmethod
    def _is_stale_cr(cr: dict[str, Any]) -> bool:
        """CR 最后更新超过 _COLD_START_SKIP_HOURS → True (冷启动跳过, 不查 DDB)。

        取 status.conditions 中最大的 lastTransitionTime 作为最后更新时间
        (conditions 数组顺序由 operator 决定, 不保证按时间排, 故取 max 而非末位);
        无 conditions 回退 metadata.creationTimestamp。解析失败不跳过 (保守)。
        ISO8601 字典序 == 时间序, 故 max 字符串即最新。
        """
        conds = ((cr.get("status") or {}).get("conditions")) or []
        times = [
            c.get("lastTransitionTime") or ""
            for c in conds
            if c.get("lastTransitionTime")
        ]
        ts_str = max(times) if times else (cr.get("metadata") or {}).get("creationTimestamp")
        if not ts_str:
            return False
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            return age_hours > _COLD_START_SKIP_HOURS
        except (ValueError, TypeError):
            return False

    # --- 写 DDB (A3 混合写入模型: 部分更新只动状态字段, 不碰 create 写的业务字段) ---
    async def _reconcile(self, cr: dict[str, Any]) -> None:
        ids = await self.resolve_ids(cr)
        if ids is None:
            return
        resource_id, ws_id = ids
        meta = cr.get("metadata") or {}
        labels = meta.get("labels") or {}
        rv = int(meta.get("resourceVersion") or 0)
        md = await self.derive_status_md(cr)
        # 部分更新: 只 SET metadata 的状态字段 (phase 等), 不覆盖 create 写的业务字段。
        result = await ri_repo.update_status_if_changed(
            workspace_id=ws_id,
            resource_type=self.resource_type,
            resource_id=resource_id,
            resource_version=rv,
            md=md,
        )
        if result == "absent":
            # 行不存在 = CLI/kubectl 绕过 UI 提交, DDB 无记录 → 建残缺行 (业务字段空, 仅状态)
            await ri_repo.create_stub(
                workspace_id=ws_id,
                resource_type=self.resource_type,
                resource_id=resource_id,
                resource_version=rv,
                creator_user_id=labels.get("platform.hyperpod.io/creator-id") or "unknown",
                k8s_namespace=meta.get("namespace") or "",
                k8s_name=meta.get("name") or "",
                resource_kind=self.resource_kind,
                display_name=meta.get("name") or "",
                md=md,
            )
            result = "created"
        # status=md (子类状态字段 dict) 便于 debug 事件演变。
        self.log.info(
            "reconcile id=%s rv=%s result=%s name=%s status=%s",
            resource_id, rv, result, meta.get("name"), md,
        )
        # 待补偿队列联动: ks=None (非终态查不到 Workload, 子类已把终态编码为 Finished)
        # → 入队待后台补; ks 有值 → 已确定, 出队 (覆盖"补成功"与"被正常事件抢先补上")。
        self._update_backfill(resource_id, ws_id, cr, md.get("kueue_status"))

    async def _mark_deleted(self, cr: dict[str, Any]) -> None:
        ids = await self.resolve_ids(cr)
        if ids is None:
            return
        resource_id, ws_id = ids
        # 用户主动停止会删 CR → informer 收 DELETED。但停止要保留 DDB 行 (前端可查
        # 日志/克隆), 不能软删 → 跳过 mark_deleted。
        # 关键: 不能查 phase! phase 是 informer 领域字段, 每个 watch 事件 partial
        # UpdateItem 持续覆盖, mark_stopped 写的 phase=Stopped 会被冲回 CR 派生值
        # (Running 等)。改查 stop_requested 哨兵 — informer 从不写此字段, 故存活。
        # 区别于真删除 (delete_flow 走 DELETE 端点, 直接 mark_deleted, 不依赖 informer)。
        existing = await ri_repo.get_resource(ws_id, self.resource_type, resource_id)
        if ((existing or {}).get("metadata") or {}).get("stop_requested"):
            self.log.info("mark_deleted.skip id=%s (stop_requested, 主动停止保留)", resource_id)
            return
        await ri_repo.mark_deleted(ws_id, self.resource_type, resource_id)
        self._backfill.pop(resource_id, None)  # CR 删除 → 出队 (不再补已删任务)
        self.log.info("mark_deleted id=%s", resource_id)

    async def _safe_reconcile(self, cr: dict[str, Any]) -> None:
        try:
            await self._reconcile(cr)
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            meta = (cr or {}).get("metadata") or {}
            self.log.error(
                "reconcile.error cr=%s/%s err=%s total_errors=%d",
                meta.get("namespace"), meta.get("name"), exc, self._error_count,
            )

    async def _safe_mark_deleted(self, cr: dict[str, Any]) -> None:
        try:
            await self._mark_deleted(cr)
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            meta = (cr or {}).get("metadata") or {}
            self.log.error(
                "mark_deleted.error cr=%s/%s err=%s total_errors=%d",
                meta.get("namespace"), meta.get("name"), exc, self._error_count,
            )

    # --- kueue_status 待补偿队列 ---
    def backfill_queue_size(self) -> int:
        """当前待补偿条数 (供 backfill 循环 log / 生产观测积压)。"""
        return len(self._backfill)

    def _update_backfill(
        self,
        resource_id: str,
        ws_id: str,
        cr: dict[str, Any],
        ks: str | None,
        *,
        now: float | None = None,
    ) -> None:
        """reconcile 派生出 ks 后联动队列: None→入队(存快照), 有值→出队。

        入队幂等: 已在队列只保留原 enqueued_at (不重置放弃时限), 刷新 CR 快照。
        存 ws_id 供 backfill 重查前查 DDB (短路已被别处写值/已删的项)。
        """
        if ks is not None:
            self._backfill.pop(resource_id, None)
            return
        t = time.monotonic() if now is None else now
        existing = self._backfill.get(resource_id)
        if existing is None:
            self._backfill[resource_id] = {
                "ws_id": ws_id,
                "cr": cr,
                "enqueued_at": t,
                "next_at": t + _BACKFILL_RETRY_INTERVAL,
                "interval": _BACKFILL_RETRY_INTERVAL,
            }
        else:
            existing["cr"] = cr  # 刷新快照, 但保留 enqueued_at / 退避节奏

    async def _run_backfill_once(self, *, now: float | None = None) -> None:
        """扫一遍待补偿队列, 对到期 (now>=next_at) 的 entry 重查派生。

        - 重查前先查 DDB: ks 已有值 (别处已写) 或行已软删 (deleted_at) → 直接出队,
          省掉一次跨集群 Workload 查询 (deleted_at 必伴随 ks=finished, 故 ks 判定已覆盖)。
        - 派生出非 None → _reconcile 内部会出队 (走 _update_backfill 有值分支)
        - 仍 None → 退避 (interval 翻倍, 上限 _BACKFILL_MAX_INTERVAL)
        - 入队超 _BACKFILL_GIVE_UP_SECONDS 仍补不上 → 放弃出队 (防死缠+泄漏)
        """
        t = time.monotonic() if now is None else now
        for rid, entry in list(self._backfill.items()):
            if t - entry["enqueued_at"] > _BACKFILL_GIVE_UP_SECONDS:
                self._backfill.pop(rid, None)
                self.log.warning(
                    "backfill.give_up id=%s (still no Workload after %ds)",
                    rid, _BACKFILL_GIVE_UP_SECONDS,
                )
                continue
            if t < entry["next_at"]:
                continue  # 未到重查时刻 (退避中)
            # 短路: DDB 已被别处写值 / 已软删 → 出队, 不必再查 Workload。
            if await self._backfill_done_in_ddb(rid, entry["ws_id"]):
                self._backfill.pop(rid, None)
                self.log.info("backfill.dequeue id=%s (ddb already has ks/deleted)", rid)
                continue
            # 重查: _reconcile 会重新派生 (实时查 Workload); 补上则内部出队。
            try:
                await self._reconcile(entry["cr"])
            except Exception as exc:  # noqa: BLE001 - 单个补偿失败不影响其他
                self.log.error("backfill.reconcile_error id=%s err=%s", rid, exc)
            # 仍在队列 = 没补上 → 退避加间隔
            still = self._backfill.get(rid)
            if still is not None:
                still["interval"] = min(still["interval"] * 2, _BACKFILL_MAX_INTERVAL)
                still["next_at"] = t + still["interval"]

    async def _backfill_done_in_ddb(self, resource_id: str, ws_id: str) -> bool:
        """查 DDB: kueue_status 已有值 (别处已写) 或行已软删 → True (不必再补)。

        查询失败不阻塞 (返 False, 走正常重查兜底)。deleted_at 与 ks=finished 绑定写入,
        故 ks 有值即覆盖"已删"情形; 仍显式查 deleted_at 作纯防御。
        """
        try:
            row = await ri_repo.get_resource(ws_id, self.resource_type, resource_id)
        except Exception as exc:  # noqa: BLE001
            self.log.info("backfill.ddb_check_skip id=%s err=%s", resource_id, exc)
            return False
        if row is None:
            return False
        if row.get("deleted_at"):
            return True
        return ((row.get("metadata") or {}).get("kueue_status")) is not None

    async def run_backfill_loop(self, hb: Any = None) -> None:
        """后台补偿循环 (尽力而为, 永不主动退出)。

        独立 task, 不写 informer 心跳 (不污染 watch 判活), 不进 supervisor。
        内部 try/except 兜住每轮, 仅极端异常才冒泡到 gather → 进程重启 (冷启动兜底)。
        hb 参数保留接口 (当前不刷, 见上)。
        """
        while True:
            await asyncio.sleep(_BACKFILL_SCAN_INTERVAL)
            try:
                if self._backfill:
                    self.log.info("backfill.queue_size=%d", len(self._backfill))
                    await self._run_backfill_once()
            except Exception as exc:  # noqa: BLE001 - 永不让循环崩
                self.log.error("backfill.loop_error err=%s", exc)

    # --- 通用 watch 循环 ---
    _LIST_PAGE_SIZE = 500  # 冷启动分页大小, 降低单次 API server 响应体 + worker 内存峰值

    async def run_one_cycle(
        self, co: Any, hb: Any, rv: str | None, *, cycle_timeout: float | None = None
    ) -> str:
        """rv=None → 冷启动分页 LIST; rv 有值 → watch 续传 (不 LIST), 周期超时强制返回。

        watch 必须用 k8s_watch.Watch().stream() (强制 _preload_content=False, 逐行真流式);
        直接 co.list_cluster_custom_object(watch=True) 会预读整个 body, 但 watch 长连接
        body 永不结束 → await 永久阻塞到周期超时 → async for 进不去 → events=0 / rv 冻结
        (真集群实证 2026-06-09: 增量 watch 从来没工作过, 只靠重启冷启动捞数据)。
        周期超时用 asyncio.timeout (抛 TimeoutError 可识别); 外部 CancelledError 不吞。
        """
        if rv is None:
            total = 0
            skipped = 0
            _continue: str | None = None
            while True:
                kwargs: dict[str, Any] = {"limit": self._LIST_PAGE_SIZE}
                if _continue:
                    kwargs["_continue"] = _continue
                resp = await co.list_cluster_custom_object(
                    self.group, self.version, self.plural, **kwargs
                )
                rv = resp["metadata"]["resourceVersion"]
                items = resp.get("items") or []
                for cr_item in items:
                    if self._is_stale_cr(cr_item):
                        skipped += 1
                        continue
                    await self._safe_reconcile(cr_item)
                total += len(items)
                hb.mark_progress()
                _continue = (resp.get("metadata") or {}).get("continue")
                if not _continue:
                    break
            self.log.info(
                "cold_start.done n=%d skipped=%d reconciled=%d rv=%s",
                total, skipped, total - skipped, rv,
            )
            return rv

        if cycle_timeout is None:
            cycle_timeout = REQUEST_TIMEOUT_SECONDS
        self.log.debug("watch.cycle start rv=%s timeout=%ss (resume, no LIST)", rv, cycle_timeout)
        events_seen = 0
        try:
            async with asyncio.timeout(cycle_timeout):
                async with k8s_watch.Watch() as w:
                    async for event in w.stream(
                        co.list_cluster_custom_object,
                        self.group, self.version, self.plural,
                        resource_version=rv,
                        timeout_seconds=SERVER_TIMEOUT_SECONDS,
                        allow_watch_bookmarks=True,
                    ):
                        etype = event.get("type")
                        obj = event.get("object") or {}
                        meta = obj.get("metadata") or {}
                        new_rv = meta.get("resourceVersion")
                        if new_rv:
                            rv = new_rv
                        events_seen += 1
                        self.log.debug(
                            "watch.event type=%s name=%s rv=%s",
                            etype, meta.get("name"), new_rv,
                        )
                        if etype == "BOOKMARK":
                            pass
                        elif etype == "DELETED":
                            await self._safe_mark_deleted(obj)
                        else:  # ADDED / MODIFIED
                            await self._safe_reconcile(obj)
                        hb.mark_progress()
        except TimeoutError:
            self.log.debug(
                "watch.cycle end rv=%s events=%d (cycle timeout, resume)", rv, events_seen
            )
        else:
            self.log.debug(
                "watch.cycle end rv=%s events=%d (stream closed, resume)", rv, events_seen
            )
        hb.mark_progress()
        return rv

    # --- 通用自愈循环 (冷启动 + 401 token 刷新 + 410 回退) ---
    async def run(self, hb: Any) -> None:
        # 同实例 spawn 后台补偿循环 (与 watch 共享 self._backfill)。
        # 跟随 run() 生命周期: run 被 supervisor cancel/重建时, 此处 finally 一并 cancel,
        # 新实例重新 spawn (dict 重置无妨, 冷启动会重新填待补偿项)。
        backfill_task = asyncio.create_task(
            self.run_backfill_loop(hb), name=f"backfill-{self.resource_type}"
        )
        try:
            await self._run_watch_forever(hb)
        finally:
            backfill_task.cancel()

    async def _run_watch_forever(self, hb: Any) -> None:
        rv: str | None = None
        consecutive_401 = 0
        while True:
            await self._load_config()
            try:
                async with ApiClient() as api:
                    co = k8s_client.CustomObjectsApi(api)
                    while True:
                        try:
                            rv = await self.run_one_cycle(co, hb, rv)
                            consecutive_401 = 0
                        except ApiException as exc:
                            if exc.status == 410:
                                self.log.warning("rv expired (410), cold-start again")
                                rv = None
                                continue
                            raise
            except ApiException as exc:
                if exc.status == 401:
                    consecutive_401 += 1
                    if not should_retry_after_401(consecutive_401):
                        self.log.error(
                            "401 after %d reloads, real auth problem, giving up",
                            consecutive_401,
                        )
                        raise
                    self.log.warning(
                        "401 (likely token expired), reload+reconnect "
                        "(attempt %d/%d), resume rv=%s",
                        consecutive_401, _MAX_401_RETRIES, rv,
                    )
                    reset_config_cache(self._context)
                    continue
                raise
