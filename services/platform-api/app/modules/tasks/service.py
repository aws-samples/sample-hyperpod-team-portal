"""任务总览聚合编排: 1 次 DDB 读 → 逐行映射 → 排序 + 统计。

读放大锁死: build_overview 只调一次 ri_repo.list_by_workspace, 其余全内存算。
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.security import is_ws_admin
from app.modules.priority.orchestration.service import _ws_namespace
from app.modules.shared.kueue_status import (
    KUEUE_ADMITTED, KUEUE_EVICTED, KUEUE_PODS_READY, KUEUE_QUEUED,
    KUEUE_QUOTA_RESERVED, is_terminal, worst_kueue_status,
)
from app.repositories import resource_index as ri_repo

logger = get_logger(__name__)

# 读侧"终态但仍占卡"过滤例外: 这些类型 kueue_status=Finished 时 active_ws 仍可能是
# controller 故意保留的合法活跃行 (占卡), 不能按 is_terminal 滤掉。
#   - train: 失败 Pod 占卡 (cleanPodPolicy, informer occupying)。
#   - rayjob: 成功/失败后 pod 仍在 ttl(关闭 timeout) 窗口占 GPU, RayCluster 未删 →
#     controller 据 RayCluster 存在保留 active_ws (bob-ray-12 实测)。
_OCCUPYING_EXEMPT_TYPES = (
    ri_repo.RESOURCE_TYPE_TRAIN,
    ri_repo.RESOURCE_TYPE_RAYJOB,
)


def format_gpu_spec(kind: str, metadata: dict[str, Any]) -> str:
    """三类总 GPU 数统一格式 "{N} GPU"; N=0 → "CPU"。缺字段当 0。"""
    if kind == "dev":
        n = int(metadata.get("gpu_count") or 0)
    elif kind == "train":
        n = int(metadata.get("node_count") or 0) * int(
            metadata.get("gpu_per_node") or 0
        )
    elif kind == "inference":
        n = int(metadata.get("replicas") or 0) * int(
            metadata.get("gpu_per_replica") or 0
        )
    elif kind == "dynamo":
        # 多机推理: 节点数 × 单节点 GPU (模板锁单节点规格, 与 dynamo List 页"规模"列同源)
        n = int(metadata.get("node_count") or 0) * int(
            metadata.get("gpu_per_worker") or 0
        )
    elif kind == "llmd":
        # llm-d 多机推理: 每副本 nodes_per_replica 个 Pod, 每 Pod gpu_per_pod 个 GPU,
        # 共 replicas 个副本 (B1 统一总卡数显示)。
        n = (
            int(metadata.get("gpu_per_pod") or 0)
            * int(metadata.get("nodes_per_replica") or 0)
            * int(metadata.get("replicas") or 0)
        )
    elif kind == "rayjob":
        # Ray 任务: worker 总卡 (worker_replicas × gpu_per_node) + head 卡 (head 通常 0)。
        n = int(metadata.get("worker_replicas") or 0) * int(
            metadata.get("gpu_per_node") or 0
        ) + int(metadata.get("head_gpu") or 0)
    else:
        n = 0
    return f"{n} GPU" if n > 0 else "CPU"


def _to_row(
    item: dict[str, Any], priority_values: dict[str, int]
) -> dict[str, Any]:
    kind = item.get("resource_type")
    md = item.get("metadata") or {}
    phase = md.get("phase")
    pc = md.get("priority_class")
    ks = md.get("kueue_status")
    if kind == "llmd":
        # llm-d 双组件 (LWS + gateway) 取最差: 都好才能服务 (组件 AND)。
        # 半删态 (LWS Finished, gateway 还活着) 合并出非终态 → active_only 过滤不误杀。
        ks = worst_kueue_status(ks, md.get("gateway_kueue_status"))
    return {
        "id": item.get("resource_id"),
        "kind": kind,
        "name": item.get("display_name"),
        # k8s_name = CR name, 前端改优先级调 priority 模块端点需 cr_name (按 ownerRef 反查 Workload)
        "k8s_name": item.get("k8s_name"),
        # status = 原始 CR phase 字符串 (去 unified; 前端直接展示不翻译)
        "status": phase,
        "creator": item.get("creator_user_id"),
        "priority_class": pc,
        "priority_value": priority_values.get(pc) if pc else None,
        "gpu_spec": format_gpu_spec(kind, md),
        "created_at": item.get("created_at"),
        "started_at": md.get("started_at"),
        "deleted_at": item.get("deleted_at"),
        # kueue_status = informer 写的三态 (queued/started/finished), 供 stats 统计同源
        # (llmd 取 LWS 与 gateway 最差合并态)
        "kueue_status": ks,
    }


async def build_overview(
    workspace_id: str,
    *,
    current_user: dict[str, Any] | None = None,
    active_only: bool = False,
    priority_values: dict[str, int] | None = None,
) -> dict[str, Any]:
    """全 workspace 视图: 返回 {stats, tasks}。整页唯一一次 DDB 读。

    active_only=True 时 DDB 层排除终态 (已完成/已失败/已停止), 供"仅显示活跃任务"。
    注意: stats 基于"活跃 (非软删) 行", 即跳过有 deleted_at 的行; 而 tasks 列表仍
    含软删行 (stop_requested 豁免行保留供查日志/克隆)。两者口径不同是有意的。

    priority_values: WPC 名字→数值 rank 映射 (router 传入, 来自一次 K8s
    list_priority_classes)。每行按 priority_class 查表填 priority_value; 无/未知
    → None。

    排序: 优先级降序 (高→低) → 同优先级内 created_at 升序 (先进先出)。
    priority_value 为 None (未知 WPC / K8s 不可达退化) 当最低优先级排最后。

    注: ri_repo.list_by_workspace 默认 limit=200。单个 workspace 任务数 (含已完成
    历史) 超 200 会被截断。M1 阶段单 workspace 远不到此量, 接受默认。若将来需要,
    分页是另一个 spec 的事 (YAGNI)。
    """
    pv = priority_values or {}
    if active_only:
        # 走稀疏 GSI active-index: 只读活跃行, 不扫全历史分区。
        items = await ri_repo.list_active_by_workspace(workspace_id)
        # 二次过滤: 推理/开发机 GSI 可能混入终态僵尸行 (active_ws 该删没删的残留) → 滤掉。
        # 占卡例外 (见 _OCCUPYING_EXEMPT_TYPES): train + rayjob 的 Finished 行可能是
        # controller 故意保留的合法活跃行 (占卡), 不能按 is_terminal 滤掉:
        #   - train: Failed Pod 占卡 (cleanPodPolicy), 须用户删 CR 才释放 → active_ws 故意留。
        #   - rayjob: 成功/失败后 Pod 在 ttl(关闭 timeout) 窗口内仍占 GPU, RayCluster 未删
        #     → controller 据 RayCluster 存在保留 active_ws (bob-ray-12 实测)。
        # 推理/开发机无此机制, Finished = 真僵尸, 一律滤掉。
        def _effective_ks(it: dict[str, Any]) -> str | None:
            md = it.get("metadata") or {}
            ks = md.get("kueue_status")
            if it.get("resource_type") == ri_repo.RESOURCE_TYPE_LLMD:
                # llmd 半删态 (LWS Finished, gateway 活着) 原始 kueue_status 是终态,
                # 但合并后非终态 → 用合并态判定, 过滤不误杀 (与 _to_row 同源)。
                return worst_kueue_status(ks, md.get("gateway_kueue_status"))
            return ks

        items = [
            it for it in items
            if it.get("resource_type") in _OCCUPYING_EXEMPT_TYPES
            or not is_terminal(_effective_ks(it))
        ]
    else:
        # 看全部 (含历史) 仍走主表
        items = await ri_repo.list_by_workspace(workspace_id, active_only=False)
    rows = [_to_row(it, pv) for it in items]
    # 排序: 优先级降序 (高→低), 同优先级内 created_at 升序 (先进先出)。
    # priority_value 为 None (未知 WPC / K8s 不可达退化) 当最低优先级排最后。
    # key 用 (-priority_value, created_at): priority 取负使大值靠前; created_at
    # 升序天然 FIFO。None → 用 float("-inf") 的相反数 (即 +inf 的负) 沉底。
    def _sort_key(r: dict[str, Any]) -> tuple[float, str]:
        pval = r.get("priority_value")
        rank = -float(pval) if pval is not None else float("inf")
        return (rank, r.get("created_at") or "")

    rows.sort(key=_sort_key)

    # stats 按六态分组 (informer 写, 与总览过滤同源):
    #   running 桶 = QuotaReserved/Admitted/PodsReady (已拿配额: 启动中/运行中) + 旧 started
    #   queued 桶  = Queued (真排队, 等配额) + Evicted (被抢占踢回重新等) + 旧 queued
    #   终态 (Finished/旧 finished) 不计 (active_only 已滤; 软删行自然不计)。
    # 注: QuotaReserved 已离开排队队列 (拿到配额), 归 running 不归 queued。
    _RUNNING = {KUEUE_QUOTA_RESERVED, KUEUE_ADMITTED, KUEUE_PODS_READY, "started"}
    _QUEUED = {KUEUE_QUEUED, KUEUE_EVICTED, "queued"}

    def _ks(r: dict[str, Any]) -> str:
        return r.get("kueue_status") or ""

    running = sum(1 for r in rows if _ks(r) in _RUNNING)
    queued = sum(1 for r in rows if _ks(r) in _QUEUED)
    can_edit = await is_ws_admin(workspace_id, current_user)
    return {
        "can_edit_priority": can_edit,
        "stats": {"running_starting": running, "queued": queued},
        "tasks": rows,
    }


# Grove PodCliqueSet 上由 NVIDIA operator 注入的 label, 其 value 一字不差 = DGD (CR) 名。
# 已实测确认 (2026-07-16)。
_DYNAMO_DGD_LABEL = "nvidia.com/dynamo-graph-deployment-name"


def _owner_to_k8s_name(
    owner_kind: str,
    owner_name: str,
    dynamo_pcs_to_dgd: dict[str, str] | None = None,
) -> str:
    """pendingworkload 的 ownerReferences[0] → 任务 CR name (= TaskRow.k8s_name)。

    真集群实证: 五类任务 Workload owner 不同层级:
    - llm-d LWS: owner=LeaderWorkerSet/<task>-multi → strip -multi → <task>。
    - 训练: owner=HyperPodPyTorchJob CR 自己, name 即 k8s_name, 原样返回。
    - llm-d gateway: owner=Pod/<task>-gateway-<rs>-<suf> → 识别 -gateway- 中缀截取 <task>。
    - dynamo (多机推理): owner=业务 Pod, 但 Pod 名切不出 DGD 名 (Grove PodCliqueSet 名
      把 CR 名截断到 24 字符 + 哈希, 见 2026-07-16 实测) → 按 PCS 名前缀匹配 owner Pod 名
      (Pod 名 = "{PCS名}-{角色}-{后缀}"), 命中取该 PCS 的 DGD label 值。
    - 推理/开发机: owner=业务 Pod, 名形如 <deployment>-<rs哈希>-<pod后缀>,
      rsplit('-', 2)[0] 取回 deployment 名; 开发机 deployment 带 workspace- 前缀
      (Spaces operator 约定), 推理 deployment 即 CR 名。

    dynamo_pcs_to_dgd: {PCS 名: DGD 名} 映射 (get_queue_order 一次 list PodCliqueSet 建)。
    owner Pod 名前缀命中某 PCS → dynamo (取 DGD 名, 多个前缀命中取最长最精确);
    未命中 → 回落 rsplit (推理/开发机)。免预判类型。
    """
    # llm-d LWS Workload: owner=LeaderWorkerSet/<task>-multi → 裸 <task>。
    if owner_kind == "LeaderWorkerSet":
        return owner_name[: -len("-multi")] if owner_name.endswith("-multi") else owner_name
    if owner_kind != "Pod":
        return owner_name
    # llm-d gateway Workload: owner=Pod/<task>-gateway-<rs>-<suf> → 裸 <task>。
    # gateway Pod 名唯一含 "-gateway-" 中缀 (dynamo/推理/开发机 Pod 无), 据此识别。
    gw_idx = owner_name.find("-gateway-")
    if gw_idx != -1:
        return owner_name[:gw_idx]
    if dynamo_pcs_to_dgd:
        best_pcs: str | None = None
        for pcs in dynamo_pcs_to_dgd:
            if owner_name == pcs or owner_name.startswith(pcs + "-"):
                if best_pcs is None or len(pcs) > len(best_pcs):
                    best_pcs = pcs
        if best_pcs is not None:
            return dynamo_pcs_to_dgd[best_pcs]
    deployment = owner_name.rsplit("-", 2)[0]
    if deployment.startswith("workspace-"):
        return deployment[len("workspace-") :]
    return deployment


async def _build_dynamo_pcs_map(namespace: str, k8s) -> dict[str, str]:
    """一次 list 该 ns 全部 Grove PodCliqueSet → {PCS 名: DGD 名 (= label 值)}。

    PCS 每 DGD 一个 (非 per-pod), 且不随 pending Pod 抖动重建 → 比 list Pod 更稳、量更小。
    PCS 名 = Pod 名前缀 (CR 名 > 24 字符时被截断 + 哈希, 故 DGD 名必须取 label 值, 不能
    拿 PCS 名当 DGD 名)。查失败 → 空映射 (静默降级, owner 回落 rsplit, 不阻塞总览)。
    """
    try:
        pcs_list = await k8s.list_podcliquesets(namespace)
    except Exception:  # noqa: BLE001
        logger.warning("queue_order.dynamo_pcs_list_fail ns=%s", namespace, exc_info=True)
        return {}
    out: dict[str, str] = {}
    for p in pcs_list:
        meta = p.get("metadata") or {}
        name = meta.get("name")
        dgd = (meta.get("labels") or {}).get(_DYNAMO_DGD_LABEL)
        if name and dgd:
            out[str(name)] = str(dgd)
    return out


async def get_queue_order(workspace_id: str, k8s) -> dict[str, dict[str, Any]]:
    """查 Kueue pendingworkloads → {任务CR名: {position: min, workloads: [{name, position, priority} 升序]}}。

    workloads 明细每项 = {name, position, priority}: priority 直接透传 pendingworkloads
    item 自带的 top-level priority (缺失回落 0), 零额外查询; workloads 仍按 position 升序。

    ws 级 namespace → LocalQueue 名 <ns>-localqueue → 实时查, 不落库。
    Kueue 不可达 / LocalQueue 不存在 / 任何异常 → 返回空映射 (静默降级, 不阻塞总览)。

    按 ownerReferences[0] 经 _owner_to_k8s_name 归一回 TaskRow.k8s_name。dynamo 一任务
    多 Pod → 多 Workload → 多 position, 同 CR 名聚合取 min (最靠前的脚 = 任务排队身位);
    训练/推理单 Workload min=那一个, 行为不变。dynamo 归一需 Pod→DGD 映射表, 仅当
    确有 Pod owner 时才 batch list 一次 (纯训练排队场景零额外调用)。
    """
    ns = await _ws_namespace(workspace_id)
    lq = f"{ns}-localqueue"
    try:
        items = await k8s.list_pending_workloads(ns, lq)
    except Exception:  # noqa: BLE001
        logger.warning("queue_order.fetch_fail ws=%s", workspace_id, exc_info=True)
        return {}

    # 仅当本次有 Pod owner (推理/开发机/dynamo) 时才建 dynamo 映射表 (纯训练场景免这次 list)。
    has_pod_owner = any(
        ((it.get("metadata") or {}).get("ownerReferences") or [{}])[0].get("kind") == "Pod"
        for it in items
    )
    dynamo_pcs_to_dgd = (
        await _build_dynamo_pcs_map(ns, k8s) if has_pod_owner else {}
    )

    # 按 CR 名聚合: position=min (最靠前身位), workloads=全部明细 (原始透传)。
    # 一任务多 Workload (llmd 多 group / gateway 多副本 / dynamo 多 Pod / 推理多副本):
    # 主 position 取 min, 明细全给前端 (展开可查)。结构对所有类型统一。
    grouped: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        meta = it.get("metadata") or {}
        owners = meta.get("ownerReferences") or []
        owner = owners[0] if owners else None
        pos = it.get("positionInLocalQueue")
        wl_name = meta.get("name")
        if owner is None or owner.get("name") is None or pos is None:
            continue
        k8s_name = _owner_to_k8s_name(
            str(owner.get("kind") or ""), str(owner["name"]), dynamo_pcs_to_dgd
        )
        prio = it.get("priority")
        grouped.setdefault(k8s_name, []).append(
            {
                "name": str(wl_name) if wl_name else "",
                "position": int(pos),
                "priority": int(prio) if prio is not None else 0,
            }
        )
    out: dict[str, dict[str, Any]] = {}
    for name, wls in grouped.items():
        wls.sort(key=lambda w: w["position"])
        out[name] = {"position": wls[0]["position"], "workloads": wls}
    return out
