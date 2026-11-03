"""Backward-compat shim · re-export from app.modules.quota.api.schemas.

Wave 2 重构 (2026-05-12) 把 schemas 搬到 api/schemas.py.
"""

from app.modules.quota.api.schemas import (
    AbsoluteBorrowLimit,
    ActivationState,
    ClusterQuotaList,
    ClusterQuotaTotals,
    ComputeQuota,
    ComputeQuotaResource,
    ComputeQuotaTarget,
    CreateComputeQuotaPayload,
    PreemptTeamTasks,
    QuotaModel,
    QuotaResourceUsage,
    QuotaStatus,
    QuotaUsage,
    ResourceSharingConfig,
    ResourceSharingStrategy,
    TotalsUsage,
    UpdateComputeQuotaPayload,
)

__all__ = [
    "AbsoluteBorrowLimit",
    "ActivationState",
    "ClusterQuotaList",
    "ClusterQuotaTotals",
    "ComputeQuota",
    "ComputeQuotaResource",
    "ComputeQuotaTarget",
    "CreateComputeQuotaPayload",
    "PreemptTeamTasks",
    "QuotaModel",
    "QuotaResourceUsage",
    "QuotaStatus",
    "QuotaUsage",
    "ResourceSharingConfig",
    "ResourceSharingStrategy",
    "TotalsUsage",
    "UpdateComputeQuotaPayload",
]
