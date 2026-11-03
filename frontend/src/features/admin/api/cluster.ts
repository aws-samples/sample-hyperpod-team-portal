/**
 * Cluster API — wraps GET /clusters, /clusters/{tag}, /clusters/{tag}/summary.
 * Types mirror the backend response shape as of 2026-05-08.
 *
 * Owned by the admin feature (cluster list + summary powers admin dashboards).
 * Other features (workspace) import via the `@/api/cluster` shim for now;
 * they'll migrate to their own features in later waves.
 */
import { apiFetch } from '@/shared/api';

export type ClusterState = 'InService' | 'Creating' | 'Updating' | 'Failed' | 'Deleting' | string;
export type SyncStatus = 'in_sync' | 'out_of_sync' | 'aws_unavailable' | string;

export interface ClusterListItem {
  id: string;
  cluster_tag: string;
  type: 'hyperpod' | 'eks' | string;
  region: string;
  state: ClusterState;
  workspace_scope: 'shared' | 'dedicated' | string;
  last_synced_at: string | null;
  created_at: string;
}

// 真 API 返 group_name/count/target(来自 DB snapshot),不是 name/current_count/target_count
export interface InstanceGroupDB {
  group_name: string;
  instance_type: string;
  count: number;
  target: number;
  az?: string;
  gpus_total?: number;
  gpus_used?: number;
  gpus_pending?: number;
  [k: string]: unknown;
}

// 真 API 返 instance_group_name(来自 AWS describe_cluster),字段不同于 DB
export interface InstanceGroupLive {
  instance_group_name: string;
  instance_type: string;
  current_count: number;
  target_count: number;
  life_cycle_config?: unknown;
  execution_role?: string;
  threads_per_core?: number;
  status?: string;
  [k: string]: unknown;
}

export interface HealthSummary {
  ready: number;
  notready: number;
  unknown: number;
  total: number;
}

export interface QuotaItem {
  workspace_id: string;
  flavor: string;
  gpu_quota: number;
  gpu_used: number;
  utilization_pct: number;
}

export interface AdvancedFeatureDetail {
  enabled: boolean;
  version?: string | null;
  [k: string]: unknown;
}

export interface AdvancedFeatures {
  // Backend returns a map of feature name → { enabled, version?, ... }.
  // Legacy prototype mock used primitives; keep union for defensive rendering.
  [feature: string]: AdvancedFeatureDetail | boolean | string | number | null;
}

export interface ClusterSummary {
  cluster: ClusterListItem;
  instance_groups_db: InstanceGroupDB[];
  instance_groups_live: InstanceGroupLive[];
  nodes_db_count: number;
  nodes_live_count: number;
  health: HealthSummary;
  quotas: QuotaItem[];
  advanced_features: AdvancedFeatures;
  sync_status: SyncStatus;
  errors: string[];
}

export function listClusters(): Promise<ClusterListItem[]> {
  return apiFetch<ClusterListItem[]>('/clusters');
}

export function getCluster(tag: string): Promise<ClusterListItem> {
  return apiFetch<ClusterListItem>(`/clusters/${encodeURIComponent(tag)}`);
}

export function getClusterSummary(tag: string): Promise<ClusterSummary> {
  return apiFetch<ClusterSummary>(`/clusters/${encodeURIComponent(tag)}/summary`);
}

export interface SyncCountDelta {
  upserted: number;
  deleted: number;
}

export interface SyncNodeDelta extends SyncCountDelta {
  ready: number;
  notready: number;
}

export interface SyncResult {
  cluster_tag: string;
  synced_at: string;
  instance_groups: SyncCountDelta;
  nodes: SyncNodeDelta;
  aws_raw: Record<string, unknown>;
  k8s_raw: Record<string, unknown>;
  errors: string[];
}

export function syncCluster(tag: string): Promise<SyncResult> {
  return apiFetch<SyncResult>(`/clusters/${encodeURIComponent(tag)}/sync`, {
    method: 'POST',
  });
}

export interface ClusterNode {
  instance_id: string;
  instance_group_name: string;
  instance_type: string;
  az: string | null;
  status: string;
  status_message?: string;
  created_at: string | null;
}

export interface ClusterNodeList {
  total: number;
  healthy: number;
  items: ClusterNode[];
}

export function listClusterNodes(tag: string): Promise<ClusterNodeList> {
  return apiFetch<ClusterNodeList>(`/clusters/${encodeURIComponent(tag)}/nodes`);
}

export interface InstanceGroupRaw {
  InstanceGroupName: string;
  InstanceType: string;
  CurrentCount: number;
  TargetCount: number;
  Status?: string;
  ExecutionRole?: string;
  ThreadsPerCore?: number;
  /** 后端回填 (us-east-1 EC2 规格): 每实例 GPU 卡数, 0 = CPU 机型。 */
  gpu_count?: number;
  /** GPU 描述如 "4×L4", CPU 机型为 null。 */
  gpu_spec?: string | null;
  /** GPU 型号如 "L4" / "H100", CPU 机型为 null。 */
  gpu_type?: string | null;
  /** 每实例 vCPU 核数。 */
  vcpu?: number;
  /** 每实例内存 GiB。 */
  memory_gib?: number;
  [k: string]: unknown;
}

export function listInstanceGroups(tag: string): Promise<InstanceGroupRaw[]> {
  return apiFetch<InstanceGroupRaw[]>(`/clusters/${encodeURIComponent(tag)}/instance-groups`);
}
