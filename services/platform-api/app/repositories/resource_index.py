"""ResourceIndex Repository — dev + train 联合索引.

K8s CR 是 source-of-truth; 此表仅做 3 类索引:
    1. 按 ws 列出所有任务: Query PK=workspace_id (SK 是随机 UUID 排序, 与时间无关;
       list_by_workspace 取回后在应用层按 created_at 重排, 见其 docstring)
    2. 按 creator 列我的所有任务: GSI creator-index
    3. 全局按类型时间筛: GSI type-time-index

主键设计:
    PK=workspace_id
    SK="<type>#<resource_id>"  e.g. "dev#abc-123" / "train#xyz-456"
    (resource_id 是随机 UUID, SK 字符串序≠创建时间序)

写入路径: 业务先建 K8s CR → 成功后写本表; K8s CR 是 SoT, 本表写失败 = 索引漏一条,
通过 reconciler/cron 兜底回填即可, 不影响数据正确性.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.adapters.ddb import base, tables
from app.modules.shared.kueue_status import KUEUE_FINISHED, is_active

RESOURCE_TYPE_DEV = tables.RESOURCE_TYPE_DEV
RESOURCE_TYPE_TRAIN = tables.RESOURCE_TYPE_TRAIN
RESOURCE_TYPE_INFERENCE = tables.RESOURCE_TYPE_INFERENCE
RESOURCE_TYPE_DYNAMO = tables.RESOURCE_TYPE_DYNAMO
RESOURCE_TYPE_RAYJOB = tables.RESOURCE_TYPE_RAYJOB
RESOURCE_TYPE_LLMD = tables.RESOURCE_TYPE_LLMD

# list_by_workspace 主表 DDB 查询侧的防御性熔断上限, 非业务展示上限 (那个由调用方
# 传入的 limit 参数控制)。远大于 limit 是必须的: SK=resource_key="<type>#<uuid>"
# 是随机 UUID 排序, 与 created_at 无关 (见下方 list_by_workspace docstring) —
# 若 DDB 侧就按 limit 截断, 截到的是随机的一批, 不是最新的一批。故这里要先把该
# ws 该类型全部未软删行捞出来 (仍是 partition-scoped query, 非全表 scan), 再在
# 应用层按 created_at 排序截断。此熔断值只防真正异常 (脏数据无限增长) 场景。
_DDB_SCAN_CAP = 50_000

VALID_TYPES = {
    RESOURCE_TYPE_DEV,
    RESOURCE_TYPE_TRAIN,
    RESOURCE_TYPE_INFERENCE,
    RESOURCE_TYPE_DYNAMO,
    RESOURCE_TYPE_RAYJOB,
    RESOURCE_TYPE_LLMD,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------- 读 ----------

async def get_resource(
    workspace_id: str, resource_type: str, resource_id: str
) -> dict[str, Any] | None:
    return await base.get_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
    )


async def list_by_workspace(
    workspace_id: str,
    *,
    resource_type: str | None = None,
    active_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """按 ws 列任务 (含 dev + train).

    传 resource_type='dev'/'train' 时只返该类型 (用 begins_with(SK, 'dev#') 高效过滤).
    active_only=True 时在 DDB 层额外排除非活跃任务: 只保留 kueue_status ∈
    {queued, started}。kueue_status 缺失 (旧行未回填 / informer 未写入 / 停止存量
    行) 一律不算活跃, 不显示。供任务总览"仅显示活跃任务"用 (真后端过滤, 非前端隐藏)。

    排序/截断注意: SK=resource_key="<type>#<uuid>", uuid 随机生成与 created_at
    无关 — DDB 层 scan_index_forward 排的是这个随机字符串, 不是时间! 若直接把
    limit 传给 DDB Query.Limit, 超过 limit 时截到的是"随机一批", 不是"最新一批"。
    故这里改为: DDB 侧只用 _DDB_SCAN_CAP 防御性熔断 (远大于 limit, 防真正异常的
    脏数据量), 取回后在应用层按 created_at 降序排序再截到 limit, 保证截断保留
    的是真正最新创建的那些。
    """
    if resource_type and resource_type not in VALID_TYPES:
        raise ValueError(f"resource_type must be one of {VALID_TYPES}")
    expr_values: dict[str, Any] = {":w": workspace_id}
    key_cond = "workspace_id = :w"
    if resource_type:
        key_cond += " AND begins_with(resource_key, :p)"
        expr_values[":p"] = f"{resource_type}#"

    # 过滤软删行 (deleted_at 由 delete_flow 真删 / informer 收 DELETED 打)。
    # 删除压倒一切: 打了 deleted_at 就不显示 (含"停止后又删除"的行)。
    # 停止行如何保留 (不被此过滤): 双保险使其 deleted_at 恒为 N —
    #   ① mark_stopped 调 clear_deleted 清残留 deleted_at;
    #   ② informer _mark_deleted 查 stop_requested 跳过软删 (不打 deleted_at)。
    # 故停止行 deleted_at 始终不存在, 此过滤自然放行, 无需额外 stop_requested 豁免。
    # (曾加的 stop_requested 豁免会让"停止后真删"的行删不掉, 已移除。)
    expr_names: dict[str, str] = {}
    filter_expr = "attribute_not_exists(deleted_at)"
    if active_only:
        # 活跃 = 非终态。终态 = Finished (新六态) 或 finished (存量旧值), 两者都排。
        # 只依赖 kueue_status: 缺字段 (老数据 / informer 未写入 / 停止存量行) 一律不算活跃,
        # 不显示。(老数据不回填; 新任务 informer 秒级写入后即显。)
        expr_names["#md"] = "metadata"
        expr_names["#ks"] = "kueue_status"
        expr_values[":fin_new"] = "Finished"
        expr_values[":fin_old"] = "finished"
        filter_expr += (
            " AND ( attribute_exists(#md.#ks) "
            "AND #md.#ks <> :fin_new AND #md.#ks <> :fin_old )"
        )

    items = await base.query(
        tables.RESOURCE_INDEX_TABLE,
        key_condition_expression=key_cond,
        expression_values=expr_values,
        expression_names=expr_names,
        filter_expression=filter_expr,
        scan_index_forward=False,
        limit=_DDB_SCAN_CAP,
    )
    items.sort(key=lambda it: it.get("created_at") or "", reverse=True)
    return items[:limit]


async def list_by_creator(
    creator_user_id: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return await base.query(
        tables.RESOURCE_INDEX_TABLE,
        key_condition_expression="creator_user_id = :c",
        expression_values={":c": creator_user_id},
        index_name=tables.RESOURCE_INDEX_GSI_CREATOR,
        scan_index_forward=False,
        limit=limit,
    )


async def list_active_by_workspace(
    workspace_id: str, *, limit: int = 200
) -> list[dict[str, Any]]:
    """走稀疏 GSI active-index 列某 ws 的活跃行 (kueue_status ∈ {queued, started})。

    只读活跃行, 不扫全历史分区。created_at 倒序。
    过滤软删行: attribute_not_exists(deleted_at) — 与主表 list_by_workspace 同口径。
    兜底"软删行 active_ws 残留进 GSI"的不一致 (如 informer reconcile 复活已软删行)。
    """
    return await base.query(
        tables.RESOURCE_INDEX_TABLE,
        key_condition_expression="active_ws = :w",
        expression_values={":w": workspace_id},
        index_name=tables.RESOURCE_INDEX_GSI_ACTIVE,
        filter_expression="attribute_not_exists(deleted_at)",
        scan_index_forward=False,
        limit=limit,
    )


async def get_by_resource_id(resource_id: str) -> dict[str, Any] | None:
    """按业务 resource_id 精确取单行 (走 resource_id-index GSI)。

    替代各 crud `_find_by_id` 的 list_by_type 全类型分区扫 + 内存轮询 (O(n)→O(1))。
    by-id 路由扁平 /{id} 无 workspace_id (主表 PK), 只能靠此 GSI 精确定位。
    resource_id 全表唯一, 命中返回 1 条; 未命中返回 None。GSI Projection=ALL,
    返回整行 (与主表一致), 供调用方 _ri_to_* 反序列化。
    """
    items = await base.query(
        tables.RESOURCE_INDEX_TABLE,
        key_condition_expression="resource_id = :r",
        expression_values={":r": resource_id},
        index_name=tables.RESOURCE_INDEX_GSI_RESOURCE_ID,
        limit=1,
    )
    return items[0] if items else None


async def list_by_type(
    resource_type: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    if resource_type not in VALID_TYPES:
        raise ValueError(f"resource_type must be one of {VALID_TYPES}")
    return await base.query(
        tables.RESOURCE_INDEX_TABLE,
        key_condition_expression="resource_type = :t",
        expression_values={":t": resource_type},
        index_name=tables.RESOURCE_INDEX_GSI_TYPE_TIME,
        scan_index_forward=False,
        limit=limit,
    )


# ---------- 写 ----------

async def upsert_resource(
    *,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    creator_user_id: str,
    k8s_namespace: str,
    k8s_name: str,
    resource_kind: str,
    display_name: str,
    metadata: dict[str, Any] | None = None,
    active_ws: str | None = None,
) -> dict[str, Any]:
    """upsert 而非 create-only — 索引表幂等回填友好.

    `created_at` 仅初次写入取 now; 已存 row 保留旧值, 防 sync reconcile 把
    创建时间刷成最近一次同步时间.
    """
    if resource_type not in VALID_TYPES:
        raise ValueError(f"resource_type must be one of {VALID_TYPES}")
    existing = await get_resource(workspace_id, resource_type, resource_id)
    created_at = (existing or {}).get("created_at") or _now_iso()
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "resource_key": tables.resource_key(resource_type, resource_id),
        "resource_type": resource_type,
        "resource_id": resource_id,
        "creator_user_id": creator_user_id,
        "k8s_namespace": k8s_namespace,
        "k8s_name": k8s_name,
        "resource_kind": resource_kind,
        "display_name": display_name,
        "created_at": created_at,
    }
    if metadata:
        item["metadata"] = metadata
    if active_ws is not None:
        item["active_ws"] = active_ws  # 顶层属性, 稀疏 GSI active-index
    await base.put_item(tables.RESOURCE_INDEX_TABLE, item, ensure_new=False)
    return item


# 去重比对字段 (A2, 2026-06-09 确定, 真集群实证):
# informer 一个训练任务 25 事件全 wrote=True (旧条件只比 rv, rv 每次涨)。
# 改为: 仅当这几个字段任一变 (且 rv 更新) 才写。不比 message (高频变但 phase 不变)、
# 不比 rv 值本身 (进去重永远失效)。priority_class 进比对 → 管理员改优先级能落库 (阶段B闭环)。
# endpoint_url 进比对 → 推理 endpoint InService 后 operator 回填 ARN, informer 拼出
# runtime URL (此时 phase 已 Running 没变), 不比它则 skipped 永不落库 → 前端 Endpoint 列空。
# 训练/开发机无此字段 (md.get 返 None 恒定), 不触发额外写, 无副作用。
_DEDUP_FIELDS = (
    "phase", "started_at", "ended_at", "priority_class", "endpoint_url",
    "status_detail", "kueue_status",
)


def _active_ws_value(workspace_id: str, kueue_status: str | None) -> str | None:
    """活跃 -> workspace_id (写顶层 active_ws); 否则 None (不写 / REMOVE)。

    判定见 shared.kueue_status.is_active (六态除 Finished 全活跃, 含 Evicted; 兼容存量旧
    小写 queued/started)。稀疏 GSI active-index 据此只收活跃行。"""
    return workspace_id if is_active(kueue_status) else None


def _build_dedup_condition(
    *, resource_version: int, md: dict[str, Any]
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """构造去重 ConditionExpression。

    返回 (condition_expression, expression_names, expression_values)。
    语义: 首次 (行不存在) → 写; 否则要求 rv 更新 且 (任一去重字段相对 DDB 现值变化) 才写。
    比对的是 DDB 现有行的 metadata.<field> (服务端原子求值), :field 是本次新值。
    现有行缺某字段时 attribute_not_exists 命中 → 视为"变了" → 写。
    """
    names: dict[str, str] = {"#md": "metadata", "#rv": "k8s_resource_version"}
    values: dict[str, Any] = {":rv": resource_version}
    field_clauses: list[str] = []
    for f in _DEDUP_FIELDS:
        names[f"#{f}"] = f
        values[f":{f}"] = md.get(f)
        field_clauses.append(f"attribute_not_exists(#md.#{f}) OR #md.#{f} <> :{f}")
    changed = " OR ".join(field_clauses)
    cond = (
        "attribute_not_exists(workspace_id) "
        f"OR ( (attribute_not_exists(#md.#rv) OR #md.#rv < :rv) AND ( {changed} ) )"
    )
    return cond, names, values


async def upsert_resource_if_newer(
    *,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    resource_version: int,
    creator_user_id: str,
    k8s_namespace: str,
    k8s_name: str,
    resource_kind: str,
    display_name: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """informer 幂等写: 仅当 该 row 不存在 或 DDB 里 k8s_resource_version < 传入 rv 才写。

    返 True=写入, False=被条件挡掉 (已有更新/同版本 → 防多副本并发 / 重连重放 回退)。
    DynamoDB ConditionExpression 服务端原子求值, 任意副本数安全。
    created_at: 初次写 now; 已存 row 保留旧值 (防 reconcile 刷成最近同步时间)。
    """
    if resource_type not in VALID_TYPES:
        raise ValueError(f"resource_type must be one of {VALID_TYPES}")
    existing = await get_resource(workspace_id, resource_type, resource_id)
    created_at = (existing or {}).get("created_at") or _now_iso()
    md = dict(metadata or {})
    md["k8s_resource_version"] = resource_version
    item: dict[str, Any] = {
        "workspace_id": workspace_id,
        "resource_key": tables.resource_key(resource_type, resource_id),
        "resource_type": resource_type,
        "resource_id": resource_id,
        "creator_user_id": creator_user_id,
        "k8s_namespace": k8s_namespace,
        "k8s_name": k8s_name,
        "resource_kind": resource_kind,
        "display_name": display_name,
        "created_at": created_at,
        "metadata": md,
    }
    # 条件 (A2 去重): 首次写 OR (rv 更新 且 phase/started_at/ended_at/priority_class 任一变)。
    # 整行 put (写全集) 不变; 仅在四个去重字段任一变化时才落盘, 挡掉高频冗余写 (message 变/operator touch)。
    cond, names, values = _build_dedup_condition(
        resource_version=resource_version, md=md
    )
    return await base.put_item_conditional(
        tables.RESOURCE_INDEX_TABLE,
        item,
        condition_expression=cond,
        expression_names=names,
        expression_values=values,
    )


# ── 部分更新 (A3 混合写入模型): informer 只更新状态字段, 不碰 create 写的业务字段 ──
# 状态字段 = informer 维护的动态字段 (从 CR 推)。业务字段 (image/instance_type/...) 由
# create 写, informer 用 update_item 点路径只 SET 这些状态子字段, 整行其余不动。
_STATUS_FIELDS = (
    "phase",
    "started_at",
    "ended_at",
    "last_condition_message",
    "priority_class",
    "status_detail",
    "kueue_status",
    "k8s_resource_version",
)


def _build_status_update_expr(
    *, workspace_id: str, resource_version: int, md: dict[str, Any]
) -> tuple[str, str, dict[str, str], dict[str, Any]]:
    """构造部分更新: UpdateExpression (只 SET metadata.<状态字段>) + 去重 ConditionExpression。

    返回 (update_expression, condition_expression, names, values)。
    去重 (= A2 同口径): rv 更新 且 phase/started_at/ended_at/priority_class 任一变; 不比 message/rv。
    """
    names: dict[str, str] = {"#md": "metadata", "#rv": "k8s_resource_version"}
    values: dict[str, Any] = {":rv": resource_version}
    set_clauses = ["#md.#rv = :rv"]
    # kueue_status=None 语义 (纯镜像修法A): "查不到Workload且CR非终态" → 保持DDB旧值,
    # 既不SET kueue_status 也不动 active_ws, 且不进去重条件 (None 不触发写)。
    ks_val = md.get("kueue_status")
    ks_present = ks_val is not None
    # SET 全部状态字段 (含 last_condition_message — 它要被写, 只是不进去重条件;
    # 含 endpoint_url — 推理 endpoint InService 后落库, 也进去重 _DEDUP_FIELDS)。
    # kueue_status 仅在有值时 SET。
    for f in (
        "phase", "started_at", "ended_at", "last_condition_message",
        "priority_class", "endpoint_url", "status_detail",
    ):
        names[f"#{f}"] = f
        values[f":{f}"] = md.get(f)
        set_clauses.append(f"#md.#{f} = :{f}")
    if ks_present:
        names["#kueue_status"] = "kueue_status"
        values[":kueue_status"] = ks_val
        set_clauses.append("#md.#kueue_status = :kueue_status")

    # 顶层 active_ws 联动 (稀疏 GSI active-index)。
    # ks_val=None → 既不 SET 也不 REMOVE (保持旧值); 有值才按活跃判定重算。
    # occupying_resources (训练 Failed 但 Pod 还占卡): 此标记只用于算 active_ws,
    # 不落库 (做法1)。即使 kueue_status=Finished, 占卡 → 仍算活跃 (留在活跃列表,
    # 让占卡的失败任务可见; informer 探测 Pod phase∈{Running,Pending} 时置此标记)。
    occupying = bool(md.get("occupying_resources"))
    remove_clauses: list[str] = []
    # active_ws 失配旁路条件 (None=不加旁路, 如 ks_val=None 不动 active_ws):
    #   目标 SET   → DDB 缺 active_ws 或值不等就放行 (即使其它字段没变也写进 GSI)
    #   目标 REMOVE → DDB 有 active_ws 就放行 (即使其它字段没变也删, 否则去重 skip 致残留)
    # 修 occupying True→False 时 dedup 字段没变被 skip、active_ws 永久残留的 bug。
    active_ws_bypass: str | None = None
    if ks_present:
        active = is_active(ks_val) or occupying
        if active:
            values[":active_ws"] = workspace_id
            set_clauses.append("active_ws = :active_ws")
            active_ws_bypass = (
                "attribute_not_exists(active_ws) OR active_ws <> :active_ws"
            )
        else:
            remove_clauses.append("active_ws")
            active_ws_bypass = "attribute_exists(active_ws)"

    update_expr = "SET " + ", ".join(set_clauses)
    if remove_clauses:
        update_expr += " REMOVE " + ", ".join(remove_clauses)
    # 去重: 任一 _DEDUP_FIELDS 相对 DDB 现值变化 (现有行缺该字段也算变)。
    # kueue_status=None 时从去重字段里剔除 (None 不应触发写)。
    dedup_fields = (
        _DEDUP_FIELDS if ks_present
        else tuple(f for f in _DEDUP_FIELDS if f != "kueue_status")
    )
    dedup = [
        f"attribute_not_exists(#md.#{f}) OR #md.#{f} <> :{f}" for f in dedup_fields
    ]
    main_cond = (
        "(attribute_not_exists(#md.#rv) OR #md.#rv < :rv) "
        f"AND ( {' OR '.join(dedup)} )"
    )
    # 补写旁路: 某些字段是后加 / 迟到, 存量行 (rv 已稳定) 靠主条件 (要求 rv 增长) 永远补不上,
    # 强制写一次 (不卡 rv)。
    #   - kueue_status: 后加字段, 缺失致总览活跃筛选/stats 失准 (缺失=attribute 不存在)。
    #   - ended_at: 终态 condition 迟到, 之前 SET 成 NULL (非不存在),
    #     本次有真值时补写。判 NULL 用 attribute_type(..., NULL) (实测历史行是 {NULL:True})。
    bypasses: list[str] = []
    if ks_present:
        bypasses.append("attribute_not_exists(#md.#kueue_status)")
    if values.get(":ended_at") is not None:
        values[":null_type"] = "NULL"
        bypasses.append(
            "attribute_not_exists(#md.#ended_at) "
            "OR attribute_type(#md.#ended_at, :null_type)"
        )

    if bypasses:
        cond_expr = f"( {main_cond} ) OR " + " OR ".join(bypasses)
    else:
        cond_expr = main_cond
    # active_ws 失配旁路: 即使 dedup 字段没变, 只要 active_ws 目标值 ≠ DDB 现值就放行。
    # 修 occupying True→False (Pod 清后) 时 dedup 没变被 skip、active_ws 残留致失败任务
    # 永留活跃列表的 bug。仅在 active_ws 真失配时多写一次, 不放大写。
    if active_ws_bypass is not None:
        cond_expr = f"( {cond_expr} ) OR ( {active_ws_bypass} )"
    return update_expr, cond_expr, names, values


async def update_status_if_changed(
    *,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    resource_version: int,
    md: dict[str, Any],
) -> str:
    """部分更新状态字段 (不碰业务字段)。返回三态:
        "updated" — 条件满足, 已更新状态字段
        "skipped" — 行存在但去重命中 (四字段没变 / rv 旧)
        "absent"  — 行不存在 (调用方应走 create_stub 兜底)
    """
    update_expr, dedup_cond, names, values = _build_status_update_expr(
        workspace_id=workspace_id, resource_version=resource_version, md=md
    )
    # 整体条件: 行存在 AND 未软删 AND 去重条件。
    # 行不存在 → attribute_exists 失败 → ok=False, old=None → "absent"
    # 行存在但去重命中/已软删 → 条件失败 → ok=False, old=有值 → "skipped"
    # attribute_not_exists(deleted_at): 软删行 informer 不复活 (不 SET active_ws 重塞 GSI);
    # 软删行存在 → old 有值 → 返回 skipped (非 absent), 不会触发 create_stub 重建。
    cond = (
        "attribute_exists(workspace_id) AND attribute_not_exists(deleted_at) "
        f"AND ( {dedup_cond} )"
    )
    ok, old = await base.update_item_conditional(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
        update_expression=update_expr,
        condition_expression=cond,
        expression_names=names,
        expression_values=values,
    )
    if ok:
        return "updated"
    return "skipped" if old else "absent"


async def create_stub(
    *,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    resource_version: int,
    creator_user_id: str,
    k8s_namespace: str,
    k8s_name: str,
    resource_kind: str,
    display_name: str,
    md: dict[str, Any],
) -> dict[str, Any]:
    """CLI 兜底: 行不存在 (绕过 UI 提交) 时新建只含必填+状态字段的残缺行 (业务字段空)。"""
    status_md = {
        k: md.get(k) for k in _STATUS_FIELDS if k != "k8s_resource_version"
    }
    status_md["k8s_resource_version"] = resource_version
    return await upsert_resource(
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        creator_user_id=creator_user_id or "unknown",
        k8s_namespace=k8s_namespace,
        k8s_name=k8s_name,
        resource_kind=resource_kind,
        display_name=display_name,
        metadata=status_md,
        active_ws=_active_ws_value(workspace_id, md.get("kueue_status")),
    )


# ── 部分更新业务字段 (A4 bugfix): platform-api 写业务字段, 不碰 informer 的状态字段 ──
# 背景: 开发机接入 informer 后 DDB 有两个写入方。原 crud.update 走 upsert_resource
# (整行 PutItem) 覆盖整个 metadata, 会 ① 用 row 旧 phase 覆盖 informer 写的新 phase
# ② metadata 不含 k8s_resource_version 把 informer 的 rv 冲成 null (真集群实证:
# 停止开发机后 DDB phase 仍 Running, rv=null)。改为部分更新 (UpdateItem SET
# metadata.<业务子字段>), 只动 platform-api 负责的业务字段, 与 informer 的部分更新
# (update_status_if_changed) 写不同子字段, 互不覆盖。


def _build_business_update_expr(
    fields: dict[str, Any],
) -> tuple[str, dict[str, str], dict[str, Any]] | None:
    """构造业务字段部分更新 UpdateExpression。

    fields: 要写的业务字段 dict (如 desired_status / ssm_managed_id / display_name)。
    语义: 非 None 值 → SET metadata.<子字段>; None 值 → REMOVE metadata.<子字段>
    (清空 = 删子字段, 与原整行 PutItem "None 字段被 _dev_to_md 过滤掉 = 该字段消失"
    的语义保持一致, 例: stop 时 ssm_managed_id=None 要清空)。
    返回 (update_expression, names, values); fields 为空返 None (调用方跳过)。
    安全闸: 拒绝状态字段 (phase/started_at/ended_at/priority_class/k8s_resource_version) —
    那是 informer 的领域, platform-api 写它们会重新引入覆盖冲突。
    """
    if not fields:
        return None
    status_set = set(_STATUS_FIELDS)
    names: dict[str, str] = {"#md": "metadata"}
    values: dict[str, Any] = {}
    set_clauses: list[str] = []
    remove_clauses: list[str] = []
    for f, v in fields.items():
        if f in status_set:
            raise ValueError(
                f"'{f}' is a status field owned by informer; "
                "platform-api must not write it (use informer's update_status_if_changed)"
            )
        names[f"#{f}"] = f
        if v is None:
            remove_clauses.append(f"#md.#{f}")
        else:
            values[f":{f}"] = v
            set_clauses.append(f"#md.#{f} = :{f}")
    parts: list[str] = []
    if set_clauses:
        parts.append("SET " + ", ".join(set_clauses))
    if remove_clauses:
        parts.append("REMOVE " + ", ".join(remove_clauses))
    return " ".join(parts), names, values


async def update_business_fields(
    *,
    workspace_id: str,
    resource_type: str,
    resource_id: str,
    fields: dict[str, Any],
) -> None:
    """部分更新业务字段 (只 SET metadata.<业务子字段>, 不碰状态字段)。

    用于 platform-api 的 stop/start/改名/SSM 等操作 — 与 informer 的部分更新互不覆盖。
    行不存在 → ItemNotFound (业务操作前已 _get_or_404, 正常不会发生)。
    """
    built = _build_business_update_expr(fields)
    if built is None:
        return
    update_expr, names, values = built
    await base.update_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
        update_expression=update_expr,
        expression_values=values,
        expression_names=names,
    )


async def mark_deleted(
    workspace_id: str, resource_type: str, resource_id: str
) -> dict[str, Any]:
    # SET deleted_at + kueue_status=finished, REMOVE active_ws:
    # 删除唯一收口 (用户 delete + informer 收 DELETED), 置 finished 使 kueue_status
    # 成可靠终态标志 — sync 404 分支据它区分"已处理" vs "外部 kubectl 删"。
    return await base.update_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
        update_expression="SET deleted_at = :d, #md.#ks = :finished REMOVE active_ws",
        expression_values={":d": _now_iso(), ":finished": KUEUE_FINISHED},
        expression_names={"#md": "metadata", "#ks": "kueue_status"},
    )


async def mark_stopped_inference(
    workspace_id: str,
    resource_id: str,
    resource_type: str = RESOURCE_TYPE_INFERENCE,
    *,
    ended_at: str | None = None,
) -> dict[str, Any]:
    """推理停止: 一次部分更新 — SET 停止字段 + REMOVE 顶层 active_ws (出稀疏 GSI)。

    phase=Stopped / endpoint_url 清空 / kueue_status=finished / stop_requested=True。
    取代原整行 PutItem (inference crud.update), 避免读放大且顺带 REMOVE active_ws。

    resource_type: 默认 inference (向后兼容); Dynamo 多机推理复用同逻辑, 传 dynamo
    (停止语义一致: 删 CR 释放算力, 保留 DDB 行)。

    ended_at: 停止时刻, 不传就不写这个字段 (dynamo / rayjob 不传, 表达式与原来一致)。
    """
    names = {
        "#md": "metadata", "#phase": "phase", "#endpoint_url": "endpoint_url",
        "#kueue_status": "kueue_status", "#stop_requested": "stop_requested",
    }
    values = {
        ":phase": "Stopped",
        ":endpoint_url": None,
        ":kueue_status": KUEUE_FINISHED,
        ":stop_requested": True,
    }
    sets = [
        "#md.#phase = :phase",
        "#md.#endpoint_url = :endpoint_url",
        "#md.#kueue_status = :kueue_status",
        "#md.#stop_requested = :stop_requested",
    ]
    if ended_at is not None:
        names["#ended_at"] = "ended_at"
        values[":ended_at"] = ended_at
        sets.append("#md.#ended_at = :ended_at")
    update_expr = f"SET {', '.join(sets)} REMOVE active_ws"
    return await base.update_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
        update_expression=update_expr,
        expression_values=values,
        expression_names=names,
    )


async def mark_stopped_training(
    workspace_id: str, resource_id: str, *, ended_at: str | None = None
) -> dict[str, Any]:
    """训练停止: 部分更新 — SET phase=Stopped / kueue_status=finished /
    stop_requested=True / ended_at + REMOVE 顶层 active_ws (出稀疏 GSI)。

    训练无 endpoint_url (区别于推理 mark_stopped_inference)。stop_requested 哨兵让
    informer 收到删 CR 的 DELETED 事件时跳过软删 (保留行供查日志/克隆)。
    ended_at = 停止时刻 (停止即结束, 否则前端运行时长用当前时间一直涨)。
    """
    names = {
        "#md": "metadata", "#phase": "phase",
        "#kueue_status": "kueue_status", "#stop_requested": "stop_requested",
        "#ended_at": "ended_at",
    }
    values = {
        ":phase": "Stopped",
        ":kueue_status": KUEUE_FINISHED,
        ":stop_requested": True,
        ":ended_at": ended_at,
    }
    update_expr = (
        "SET #md.#phase = :phase, #md.#kueue_status = :kueue_status, "
        "#md.#stop_requested = :stop_requested, #md.#ended_at = :ended_at "
        "REMOVE active_ws"
    )
    return await base.update_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(
                tables.RESOURCE_TYPE_TRAIN, resource_id
            ),
        },
        update_expression=update_expr,
        expression_values=values,
        expression_names=names,
    )


async def clear_deleted(
    workspace_id: str, resource_type: str, resource_id: str
) -> dict[str, Any]:
    """REMOVE deleted_at — 停止 (Stopped 保留行) 防竞态残留软删标。

    停止删 CR 后, 并发 sync 见 CR 404 可能抢先打 deleted_at; mark_stopped 后调此清掉,
    保证 Stopped 行不被列表 attribute_not_exists(deleted_at) 过滤掉 (仍可进详情看日志)。
    """
    return await base.update_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
        update_expression="REMOVE deleted_at",
    )


async def delete_resource(
    workspace_id: str, resource_type: str, resource_id: str
) -> None:
    await base.delete_item(
        tables.RESOURCE_INDEX_TABLE,
        {
            "workspace_id": workspace_id,
            "resource_key": tables.resource_key(resource_type, resource_id),
        },
        require_exists=False,
    )
