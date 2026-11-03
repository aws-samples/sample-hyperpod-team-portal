/**
 * Public exports for the quota feature.
 *
 * Admin-level quota pages stay in `features/admin` (Wave 3 C4 scope). This
 * feature owns the AWS ComputeQuota client + the in-form QuotaPreviewBar
 * that training / inference create pages render.
 */
export { default as QuotaPreviewBar } from './components/QuotaPreviewBar';

export {
  // API calls
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
  listClusterQuotas,
  createComputeQuota,
  updateComputeQuota,
  deleteComputeQuota,
  // helpers
  aggregateQuota,
  // types
  type ComputeQuota,
  type ComputeQuotaResource,
  type ComputeQuotaTarget,
  type ResourceSharingConfig,
  type QuotaUsage,
  type QuotaUsageTotals,
  type QuotaResourceUsage,
  type WorkspaceQuotaView,
  type ClusterQuotaList,
  type CreateComputeQuotaPayload,
  type UpdateComputeQuotaPayload,
  type AggregatedQuota,
  type ActivationState,
  type QuotaStatus,
  type ResourceSharingStrategy,
  type PreemptTeamTasks,
} from './api';
