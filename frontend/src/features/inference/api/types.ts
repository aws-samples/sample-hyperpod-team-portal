/**
 * Inference TS types · 镜像 backend services/platform-api/app/modules/inference/api/schemas.py
 */

export type Framework = 'sglang';

export type ModelSourceType = 'fsx' | 's3' | 'huggingface';

export type RoutingStrategy =
  | 'roundrobin'
  | 'prefixaware'
  | 'kvaware'
  | 'session';

export type L2CacheBackend = 'redis';

export type InferencePhase =
  | 'Pending'
  | 'Provisioning'
  | 'Running'
  | 'Failed'
  | 'Stopped'
  | 'Deleted';

export type InferenceScope = 'mine' | 'all';

export interface ModelSourceFsx {
  filesystem_id: string;
  model_location: string;
  mount_name?: string | null;
  dns_name?: string | null;
}

export interface ModelSourceS3 {
  bucket_name: string;
  region: string;
  model_location: string;
  prefetch_enabled: boolean;
}

export interface ModelSourceHuggingFace {
  model_id: string;
  prefetch_enabled: boolean;
}

export interface L2KvCacheConfig {
  enabled: boolean;
  backend: L2CacheBackend;
  redis_endpoint: string;
}

export interface InferenceCreatePayload {
  // 不含 name: 后端从 display_name 派生, 传了 422。display_name 须 DNS 合法。
  display_name: string;
  description?: string | null;

  framework: Framework;
  model_source_type: ModelSourceType;
  fsx?: ModelSourceFsx | null;
  s3?: ModelSourceS3 | null;
  huggingface?: ModelSourceHuggingFace | null;
  // 不含 model_name: 后端用派生出的任务名当 modelName
  model_mount_path: string;

  instance_type: string;
  gpu_per_replica: number;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  replicas: number;

  // context_length 已并入 args 框 (--context-length), 不再单独字段
  sglang_extra_args: string[];
  // 完整 command / args override (UI 两框); 空数组 → 后端回退默认拼装
  sglang_command: string[];
  sglang_args: string[];
  // 单脚本启动: 非空 → 后端渲 command=["/bin/sh","-c"], args=[launch_script]
  launch_script?: string | null;
  image: string;

  invocation_endpoint: string;
  container_port: number;

  routing_strategy: RoutingStrategy;
  l2_kv_cache: L2KvCacheConfig;

  metrics_enabled: boolean;
  public_endpoint: boolean;
  labels: Record<string, string>;
  priority_value: number;
  env: Record<string, string>;
}

export interface InferenceListItem {
  id: string;
  workspace_id: string;
  creator_user_id: string;
  creator_display_name: string;
  name: string;
  display_name: string;
  framework: string;
  model_name: string;
  model_source_type: string;
  phase: InferencePhase | string;
  kueue_status?: string | null; // Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像)
  replicas: number;
  gpu_per_replica: number;
  instance_type: string;
  endpoint_url?: string | null;
  created_at: string;
  // 停止时刻; 未停止 / 老任务为 null (列表显示 "-")。
  ended_at?: string | null;
  last_sync_at?: string | null;
}

export interface InferenceCondition {
  type?: string;
  status?: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

export interface InferenceContainerSummary {
  name?: string;
  ready?: boolean;
  status?: string;
  restarts?: number;
  reason?: string | null; // 崩溃原文 (lastState.terminated.message)
}

export interface InferencePodSummary {
  name?: string;
  phase?: string;
  ready?: string;
  status?: string;
  restarts?: number;
  reason?: string | null; // 崩溃原文, 正常时 null
  containers?: InferenceContainerSummary[];
  node_name?: string;
  pod_ip?: string;
  host_ip?: string;
  start_time?: string;
  workload_name?: string | null; // 所属 pod 级 Kueue Workload 名 (点链接查该副本 conditions)
}

export interface InferenceDetail extends InferenceListItem {
  workspace_display_name: string; // 仅详情页用; 列表页不用故不放 ListItem (省 N 次 GetItem)
  description?: string | null;
  k8s_namespace: string;
  k8s_endpoint_name: string;
  model_mount_path?: string;
  image: string;
  invocation_endpoint: string;
  container_port: number;
  sglang_extra_args: string[];
  launch_script?: string | null;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  fsx?: ModelSourceFsx | null;
  s3?: ModelSourceS3 | null;
  huggingface?: ModelSourceHuggingFace | null;
  routing_strategy: RoutingStrategy | string;
  l2_kv_cache: L2KvCacheConfig;
  metrics_enabled: boolean;
  public_endpoint: boolean;
  alb_dns?: string | null;
  labels: Record<string, string>;
  env: Record<string, string>;
  last_condition_message?: string | null;
  conditions: InferenceCondition[];
  pods: InferencePodSummary[];
}
