"""DynamoGraphDeployment CR → 详情页实时快照.

与 inference sync 的区别: phase/kueue_status 归 Go platform-controller 落库,
本 sync 只在详情页 sync=true 时【实时拉】CR status + pod 给前端展示 (conditions
时间线 + pod 表), 不回写 DDB 状态字段 (避免和 controller 抢写)。

CR 没了 (404): 据 kueue_status 区分 —— 终态不动; 非终态 (外部 kubectl 删) mark_stopped。
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.dynamo.persistence import crud
from app.modules.shared.kueue_status import is_terminal
from app.services.k8s_client import K8sAPIError, K8sClient

logger = get_logger(__name__)

# grove 给 frontend/worker pod 打的 CR 关联 label (实测 2026-07-11)
_POD_LABEL_KEY = "nvidia.com/dynamo-graph-deployment-name"


async def sync_from_k8s(
    db: Any, k8s: K8sClient, row: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """读 CR .status.conditions + pods 给详情页实时展示。

    返回 (row, conditions, pods)。row 状态字段不改 (归 Go controller),
    仅 CR 消失时兜底 mark_stopped。
    """
    del db
    try:
        cr = await k8s.get_dynamo_deployment(
            row["k8s_namespace"], row["k8s_cr_name"]
        )
    except K8sAPIError as exc:
        if "404" in exc.code:
            if is_terminal(row.get("kueue_status")):
                return row, [], []
            row = await crud.mark_stopped(None, row)
            return row, [], []
        logger.info(
            "dynamo.sync.k8s_err",
            id=str(row.get("id")),
            code=exc.code,
            msg=exc.message,
        )
        return row, [], []

    status_ = cr.get("status") or {}
    conditions = status_.get("conditions") or []

    try:
        pods = await k8s.list_pods_by_label_selector(
            row["k8s_namespace"],
            f"{_POD_LABEL_KEY}={row['k8s_cr_name']}",
        )
    except K8sAPIError:
        pods = []

    return row, conditions, pods
