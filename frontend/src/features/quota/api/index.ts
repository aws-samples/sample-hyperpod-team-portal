/**
 * AWS HyperPod ComputeQuota API · direct pass-through (no legacy resource_quota table).
 *
 * Backend contract (services/platform-api/app/modules/quota/router.py, verified 2026-05-11):
 *   GET    /workspaces/{ws_id}/quota           → ComputeQuota
 *   GET    /workspaces/{ws_id}/quota/usage     → QuotaUsage (Kueue-backed, may 404 during degraded mode)
 *   POST   /workspaces/{ws_id}/quota           body: CreateComputeQuotaPayload → ComputeQuota (201)
 *   PATCH  /workspaces/{ws_id}/quota           body: UpdateComputeQuotaPayload → ComputeQuota
 *   DELETE /workspaces/{ws_id}/quota                                            → 204
 *   GET    /clusters/{cluster_tag}/quotas      → ClusterQuotaList
 *
 * Request/response encoding: backend Pydantic uses `alias_generator=to_camel`
 * + `populate_by_name=True`, so request bodies MUST be camelCase (that's what
 * the response schema advertises) and responses ARE camelCase. `ClusterArn` is
 * derived server-side from the workspace's cluster — the client does not send it.
 *
 * AWS response gotchas:
 * - `vCpu` and `memoryInGiB` are stubbed to 0.0 by AWS → backend refills them
 *   (us-east-1 EC2 规格, 见 _tag_resource_pools) before the client sees them.
 * - Usage is delivered by a separate endpoint; callers must `Promise.allSettled`
 *   and degrade gracefully when usage is unavailable.
 *
 * Wave 3 (C3) migration: moved from `src/api/quota.ts`.
 */
import { apiFetch } from '@/shared/api';

// ---------- Enums / literals ----------

export type ActivationState = 'Enabled' | 'Disabled';

export type QuotaStatus =
  | 'Created'
  | 'Creating'
  | 'CreateFailed'
  | 'Updating'
  | 'Updated'
  | 'UpdateFailed'
  | 'Deleting'
  | 'DeleteFailed';

/**
 * AWS `ResourceSharingConfig.Strategy` enum — three values only.
 * Backend `schemas.py::ResourceSharingStrategy` mirrors this exactly.
 */
export type ResourceSharingStrategy = 'LendAndBorrow' | 'Lend' | 'DontLend';

export type PreemptTeamTasks = 'LowerPriority' | 'Never';

// ---------- Core quota shapes (mirror AWS DescribeComputeQuota) ----------

export interface ComputeQuotaResource {
  instanceType: string;
  /** Per-instance accelerator count (not total). Multiply by `count` for total GPUs. */
  accelerators: number;
  /** Number of instances in this resource row. Total GPUs = count × accelerators. */
  count: number;
  /** 后端已用 us-east-1 EC2 规格回填 (见 _tag_resource_pools)。 */
  vCpu: number;
  /** 后端已用 us-east-1 EC2 规格回填 (见 _tag_resource_pools)。 */
  memoryInGiB: number;
  /** GPU/CPU 资源池 (后端 EC2 GpuInfo 判, 缺省按 CPU 兜底)。 */
  pool?: 'gpu' | 'cpu';
  /** GPU 描述如 "4×A10G", CPU 机型为 null。 */
  gpuSpec?: string | null;
  /** GPU 型号如 "L4" / "H100", CPU 机型为 null (后端回填)。 */
  gpuType?: string | null;
}

export interface ResourceSharingConfig {
  strategy: ResourceSharingStrategy;
  /** Percentage 0-100; meaningful only when strategy=LendAndBorrow. */
  borrowLimit?: number | null;
  /** Per-team absolute borrow caps. Shape mirrors AWS; leave as unknown[] until we wire UI. */
  absoluteBorrowLimits?: unknown[];
}

export interface ComputeQuotaTarget {
  teamName: string;
  /** Integer 1-100. Replaces legacy `priority_class` (low/normal/high). */
  fairShareWeight: number;
}

export interface ComputeQuota {
  computeQuotaArn: string;
  computeQuotaId: string;
  name: string;
  description?: string | null;
  clusterArn: string;
  activationState: ActivationState;
  status: QuotaStatus;
  computeQuotaVersion?: number;
  resources: ComputeQuotaResource[];
  sharingConfig: ResourceSharingConfig;
  preemptTeamTasks: PreemptTeamTasks;
  target: ComputeQuotaTarget;
  creationTime: string; // ISO-8601
  lastModifiedTime: string;
}

// ---------- Usage (separate Kueue-backed endpoint) ----------

export interface QuotaResourceUsage {
  instanceType: string;
  acceleratorsUsed: number;
  acceleratorsPending: number;
  vCpuUsed: number; // float cores
  memoryUsedInGiB: number; // float GiB
}

export interface QuotaUsageTotals {
  accelerators: number;
  acceleratorsPending: number;
  vCpu: number;
  memoryInGiB: number;
}

export interface QuotaUsage {
  teamName: string;
  resources: QuotaResourceUsage[];
  totals: QuotaUsageTotals;
  capturedAt: string; // ISO, freshness indicator
}

// ---------- Composed view model ----------

/**
 * Paired quota + usage snapshot consumed by dashboard widgets. `usage` is
 * null when the usage endpoint is unavailable — UI must degrade (no progress
 * fill, show "用量采集中" hint) in that case.
 */
export interface WorkspaceQuotaView {
  quota: ComputeQuota;
  usage: QuotaUsage | null;
}

// ---------- Cluster-level list (admin) ----------

export interface ClusterQuotaList {
  clusterArn: string;
  clusterTag: string;
  quotas: ComputeQuota[];
}

// ---------- Create / Update payloads ----------

/**
 * POST /workspaces/{wsId}/quota body.
 *
 * Backend derives `clusterArn` from the workspace's cluster row, so the client
 * must NOT send it. All field names follow the `to_camel` alias the backend
 * advertises in its response schema.
 */
export interface CreateComputeQuotaPayload {
  name: string;
  description?: string;
  activationState: ActivationState;
  resources: Array<
    Pick<ComputeQuotaResource, 'instanceType' | 'count'> &
      Partial<Pick<ComputeQuotaResource, 'accelerators'>>
  >;
  sharingConfig: ResourceSharingConfig;
  preemptTeamTasks: PreemptTeamTasks;
  target: ComputeQuotaTarget;
}

export type UpdateComputeQuotaPayload = Partial<
  Pick<
    CreateComputeQuotaPayload,
    | 'description'
    | 'activationState'
    | 'resources'
    | 'sharingConfig'
    | 'preemptTeamTasks'
    | 'target'
  >
>;

// ---------- API calls ----------

export function getWorkspaceQuota(wsId: string): Promise<ComputeQuota> {
  return apiFetch<ComputeQuota>(
    `/workspaces/${encodeURIComponent(wsId)}/quota`,
  );
}

export function getWorkspaceQuotaUsage(wsId: string): Promise<QuotaUsage> {
  return apiFetch<QuotaUsage>(
    `/workspaces/${encodeURIComponent(wsId)}/quota/usage`,
  );
}

export function listClusterQuotas(clusterTag: string): Promise<ClusterQuotaList> {
  return apiFetch<ClusterQuotaList>(
    `/clusters/${encodeURIComponent(clusterTag)}/quotas`,
  );
}

/**
 * Create a ComputeQuota bound to `wsId`. Backend reads the workspace's cluster
 * and attaches `ClusterArn` server-side, then writes the returned
 * `computeQuotaId` / `computeQuotaArn` back onto the workspace row.
 */
export function createComputeQuota(
  wsId: string,
  payload: CreateComputeQuotaPayload,
): Promise<ComputeQuota> {
  return apiFetch<ComputeQuota>(
    `/workspaces/${encodeURIComponent(wsId)}/quota`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

/**
 * Update the ComputeQuota bound to `wsId`. Backend does a describe-merge-update
 * cycle (AWS `UpdateComputeQuota` is whole-replace) and returns the refreshed
 * schema. Passing only the changed fields is fine; omitted fields keep their
 * current AWS value.
 */
export function updateComputeQuota(
  wsId: string,
  payload: UpdateComputeQuotaPayload,
): Promise<ComputeQuota> {
  return apiFetch<ComputeQuota>(
    `/workspaces/${encodeURIComponent(wsId)}/quota`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  );
}

/**
 * Delete the ComputeQuota bound to `wsId`. Backend clears the workspace's
 * `sagemaker_compute_quota_id/arn` columns after AWS confirms deletion.
 */
export function deleteComputeQuota(wsId: string): Promise<void> {
  return apiFetch<void>(
    `/workspaces/${encodeURIComponent(wsId)}/quota`,
    { method: 'DELETE' },
  );
}

// ---------- Aggregation helpers (frontend-side math) ----------

export interface AggregatedQuota {
  totalAccelerators: number;
  totalVCpu: number; // float cores
  totalMemoryInGiB: number; // float GiB
}

/**
 * Aggregate `ComputeQuotaResource[]` into totals. vCPU/memory/accelerators are
 * backend-filled (us-east-1 EC2 规格, 见 _tag_resource_pools); AWS's own
 * DescribeComputeQuota returns 0.0 stubs so we rely on the backend enrichment.
 */
export function aggregateQuota(
  resources: ComputeQuotaResource[],
): AggregatedQuota {
  return resources.reduce<AggregatedQuota>(
    (acc, r) => ({
      totalAccelerators: acc.totalAccelerators + r.accelerators * r.count,
      totalVCpu: acc.totalVCpu + r.vCpu * r.count,
      totalMemoryInGiB: acc.totalMemoryInGiB + r.memoryInGiB * r.count,
    }),
    { totalAccelerators: 0, totalVCpu: 0, totalMemoryInGiB: 0 },
  );
}
