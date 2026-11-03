/**
 * RayJob (Ray 训练) TS types · 镜像 backend app/modules/rayjob/api/schemas.py
 *
 * 与训练任务 UI 平级, 独立 CRD (ray.io/v1 RayJob)。模型/代码走授权 FSx (后端反查 pvc),
 * entrypoint 指 FSx 上 .sh; 资源锁单节点 (head/worker 同规格) × worker_replicas。
 */
import type { BadgeProps } from 'antd';

// phase 权威源 = Go controller 写的 jobStatus (大写); 兼容保留历史 jobDeploymentStatus 值 + Python 初值
export type RayJobPhase =
  // Go controller jobStatus (大写, 权威源; jobStatus 非空时 phase = 原样大写)
  | 'PENDING'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'STOPPED'
  // Python create 初值 + jobDeploymentStatus 值 (jobStatus 为空时 phase = "{值} (Deploy Status)")
  | 'initializing'
  | 'New'
  | 'Suspended'
  | 'Initializing'
  | 'Running'
  | 'Complete'
  | 'Failed'
  | 'Stopped';

// Go controller 在 jobStatus 为空时把 phase 写成 "{deployStatus} (Deploy Status)"。
// badge/终态判定按纯值精确匹配, 故匹配前先剥掉后缀 (展示仍用带后缀原值)。
export function barePhase(phase: string | undefined): string {
  return (phase ?? '').replace(/ \(Deploy Status\)$/, '');
}

// RayJob phase → Badge 色 (单一真相源, List/Detail 共用)。
// jobStatus (Go controller 权威源, 大写) + 历史 jobDeploymentStatus 剥后缀纯值兼容;
// 命中取色, 未命中 default。⚠️ 不用 shared/status 的 phaseColor: 那按 /Running/i 归绿,
// 会把 Ray 的 RUNNING (运行中, 该蓝) 误判成 success 绿。
export const rayPhaseBadge: Record<string, BadgeProps['status']> = {
  // Go controller jobStatus (大写, 权威源)
  PENDING: 'processing',
  RUNNING: 'processing',
  SUCCEEDED: 'success',
  FAILED: 'error',
  STOPPED: 'warning',
  // 兼容: Python 初值 + jobDeploymentStatus 剥后缀后的纯值 (New/Suspended/Initializing/Running/Complete/Failed)
  initializing: 'processing',
  New: 'default',
  Suspended: 'warning',
  Initializing: 'processing',
  Running: 'processing',
  Complete: 'success',
  Failed: 'error',
  Stopped: 'warning',
};

// 终态 phase 纯值集 (剥后缀后; List/Detail 共用判定"是否可停")。
export const RAY_TERMINAL_PHASES = [
  'Failed',
  'Complete',
  'Stopped',
  'SUCCEEDED',
  'FAILED',
  'STOPPED',
];

export type RayJobScope = 'mine' | 'all';

export interface RayEnvSecret {
  name: string;
  secret_key: string;
  secret_ref?: string;
}

// 引用 (创建时传): FSx 只传 pvc_name / S3 只传 mount_id, 后端反查授权真值
export interface FsxMountRef {
  pvc_name: string;
}
export interface S3DatasetRef {
  mount_id: string;
}
// 挂载真值 (详情/展示): 后端反查填充
export interface ExtraFsxMount {
  pvc_name: string;
  mount_path: string;
  read_only: boolean;
  gid?: number | null;
}
export interface S3DatasetMount {
  bucket: string;
  prefix: string;
  mount_path: string;
  pvc_name: string;
}

export interface RayJobCreatePayload {
  // name 由后端从 display_name 派生, 前端不传
  name?: string;
  display_name: string;
  description?: string | null;

  // head 落 CPU node 用 CPU 镜像, worker 用 gpu 镜像
  head_image: string;
  worker_image: string;

  fsx_mounts: FsxMountRef[];
  s3_datasets: S3DatasetRef[];
  entry_script_path: string;

  worker_replicas: number;

  head_instance_type: string;
  head_gpu: number;
  head_cpu_request_millicores: number;
  head_cpu_limit_millicores: number;
  head_memory_request_mib: number;
  head_memory_limit_mib: number;
  head_efa: number;
  worker_instance_type: string;
  gpu_per_node: number;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  efa_per_node: number;
  max_run_hours: number;

  ttl_seconds_after_finished: number; // KubeRay 要 ≥0
  backoff_limit: number;

  env: Record<string, string>;
  env_secrets: RayEnvSecret[];
  run_as_root: boolean;
  labels: Record<string, string>;
}

export interface RayJobListItem {
  id: string;
  workspace_id: string;
  creator_user_id: string;
  creator_display_name: string;
  name: string;
  display_name: string;
  phase: RayJobPhase | string;
  kueue_status?: string | null;
  worker_replicas: number;
  worker_instance_type: string;
  gpu_per_node: number;
  // 生命周期时刻 (controller 从 CR status.startTime/endTime 派生); 运行时长 = (ended_at ?? now) - started_at
  started_at?: string | null;
  ended_at?: string | null;
  created_at: string;
  last_sync_at?: string | null;
}

export interface RayJobCondition {
  type?: string;
  status?: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

export interface RayJobContainerSummary {
  name?: string;
  ready?: boolean;
  status?: string;
  restarts?: number;
  reason?: string | null;
}

export interface RayJobPodSummary {
  name?: string;
  role?: string | null; // head / worker (ray.io/node-type)
  phase?: string;
  ready?: string;
  status?: string;
  restarts?: number;
  reason?: string | null;
  containers?: RayJobContainerSummary[];
  node_name?: string;
  pod_ip?: string;
  host_ip?: string;
  start_time?: string;
}

export interface RayJobDetail extends RayJobListItem {
  workspace_display_name: string;
  description?: string | null;
  k8s_namespace: string;
  k8s_cr_name: string; // pod 定位锚点 (pod label ray.io/cluster=<CR名>)
  head_image: string;
  worker_image: string;
  entry_script_path?: string | null;
  extra_fsx_mounts: ExtraFsxMount[];
  s3_datasets: S3DatasetMount[];
  // head 资源 (协调节点)
  head_instance_type: string;
  head_gpu: number;
  head_cpu_request_millicores: number;
  head_cpu_limit_millicores: number;
  head_memory_request_mib: number;
  head_memory_limit_mib: number;
  head_efa: number;
  // worker 资源 (计算节点)
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  efa_per_node: number;
  max_run_hours: number;
  ttl_seconds_after_finished: number;
  backoff_limit: number;
  env: Record<string, string>;
  env_secrets: RayEnvSecret[];
  run_as_root: boolean;
  labels: Record<string, string>;
  last_condition_message?: string | null;
  conditions: RayJobCondition[];
  pods: RayJobPodSummary[];
}
