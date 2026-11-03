"""RayJob CR → 详情页实时快照.

详情页 sync=true 时实时拉 CR .status + pod 给前端 (conditions 时间线 + pod 表),
不回写 DDB 状态字段 (phase/kueue_status 归 Go platform-controller, 第二批)。

CR 没了 (404): 据 kueue_status 区分 —— 终态不动; 非终态 (外部 kubectl 删) mark_stopped。
"""

from __future__ import annotations

from typing import Any

from app.adapters.ddb import tables as _tables
from app.core.logging import get_logger
from app.modules.rayjob.persistence import crud
from app.repositories import resource_index as ri_repo
from app.modules.shared.kueue_status import is_terminal
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

# KubeRay 给 head/worker pod 打的 CR 关联 label (实测 2026-07-20)
_POD_LABEL_KEY = "ray.io/cluster"


async def sync_from_k8s(
    db: Any, k8s: K8sClient, row: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """读 RayJob .status + pods 给详情页实时展示。

    返回 (row, conditions, pods)。row 状态字段不改 (归 Go controller),
    仅 CR 消失时兜底 mark_stopped。

    ★ pod 反查用 ray.io/cluster=<rayClusterName>: RayJob 建的 RayCluster 名 =
    status.rayClusterName (带随机后缀), 非 CR 名; 从 status 取。
    """
    del db
    try:
        cr = await k8s.get_rayjob(row["k8s_namespace"], row["k8s_cr_name"])
    except K8sAPIError as exc:
        if "404" in exc.code:
            if is_terminal(row.get("kueue_status")):
                return row, [], []
            row = await crud.mark_stopped(None, row)
            return row, [], []
        logger.info(
            "rayjob.sync.k8s_err", id=str(row.get("id")), code=exc.code, msg=exc.message
        )
        return row, [], []

    status_ = cr.get("status") or {}
    ray_cluster_status = status_.get("rayClusterStatus") or {}
    conditions = ray_cluster_status.get("conditions") or []
    ray_cluster_name = status_.get("rayClusterName")

    # 回填 ray_cluster_name 到 DDB (历史日志 stream 前缀锚点; CR 被 ttl 删后仍能查历史)。
    # 只在首次拿到 / 变化时部分更新 (对称读写, 不整行 put)。
    if ray_cluster_name and row.get("ray_cluster_name") != ray_cluster_name:
        try:
            await ri_repo.update_business_fields(
                workspace_id=row["workspace_id"],
                resource_type=_tables.RESOURCE_TYPE_RAYJOB,
                resource_id=row["id"],
                fields={"ray_cluster_name": ray_cluster_name},
            )
            row["ray_cluster_name"] = ray_cluster_name
        except Exception:  # noqa: BLE001 — 回填失败不阻塞详情页
            logger.info("rayjob.sync.cache_cluster_name_fail", id=str(row.get("id")))
    else:
        row["ray_cluster_name"] = ray_cluster_name or row.get("ray_cluster_name")

    pods: list[dict[str, Any]] = []
    if ray_cluster_name:
        try:
            pods = await k8s.list_pods_by_label_selector(
                row["k8s_namespace"], f"{_POD_LABEL_KEY}={ray_cluster_name}"
            )
        except K8sAPIError:
            pods = []

    return row, conditions, pods
