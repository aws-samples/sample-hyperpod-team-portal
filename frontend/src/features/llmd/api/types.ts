// llm-d (多机推理, 分支B) TS types · 镜像 backend app/modules/llmd/api/schemas.py

export type LlmdModelSourceType = 'fsx' | 's3';

// Stopped 是平台哨兵 (stop 删 CR 保配置); 其余 phase 由 Go controller 写
export type LlmdPhase =
  | 'initializing'
  | 'pending'
  | 'successful'
  | 'failed'
  | 'Stopped';

export type LlmdScope = 'mine' | 'all';

export interface LlmdCreatePayload {
  // 不含 name: 后端从 display_name 派生, 传了 422。display_name 须 DNS 合法且 ≤20。
  display_name: string;
  description?: string | null;

  // fsx 传 model_pvc, s3 传 s3_bucket+s3_prefix (二选一, 后端反查/自建 PVC)
  model_source_type: LlmdModelSourceType;
  model_pvc?: string | null;
  s3_bucket?: string | null;
  s3_prefix?: string | null;
  launch_script: string;

  gpu_instance_type: string;
  gateway_instance_type: string;

  replicas: number;
  nodes_per_replica: number;
  gpu_per_pod: number;
  efa_per_pod: number;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;

  gateway_image: string;
  gateway_replicas: number;
  gateway_extra_args: string[];
  gateway_cpu_request_millicores: number;
  gateway_cpu_limit_millicores: number;
  gateway_memory_request_mib: number;
  gateway_memory_limit_mib: number;
  sglang_image: string;

  // 建 internal ALB 暴露 endpoint (HTTP:80 明文, 无鉴权)。只在创建时生效。
  expose_alb: boolean;

  labels: Record<string, string>;
}

export interface LlmdListItem {
  id: string;
  workspace_id: string;
  creator_user_id: string;
  creator_display_name: string;
  name: string;
  display_name: string;
  phase: LlmdPhase | string;
  kueue_status?: string | null;
  replicas: number;
  nodes_per_replica: number;
  gpu_instance_type: string;
  gpu_per_pod: number;
  // http://<alb-dns>; ALB 就绪【且】gateway 有 Ready 副本才有值, 否则为空
  endpoint_url?: string | null;
  created_at: string;
  // 停止时刻; 未停止 / 老任务为 null (列表显示 "-")。
  ended_at?: string | null;
  last_sync_at?: string | null;
}

export interface LlmdCondition {
  type?: string;
  status?: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

export interface LlmdContainerSummary {
  name?: string;
  ready?: boolean;
  status?: string;
  restarts?: number;
  reason?: string | null;
}

export interface LlmdPodSummary {
  name?: string;
  role?: string; // gateway / leader / worker
  phase?: string;
  ready?: string;
  status?: string;
  restarts?: number;
  reason?: string | null;
  containers?: LlmdContainerSummary[];
  node_name?: string;
  pod_ip?: string;
  host_ip?: string;
  start_time?: string;
  group?: string | null; // 副本组序号 (LWS pod); gateway 为 null
  workload_name?: string | null; // 所属 Kueue Workload 名 (点链接查 conditions)
}

export interface LlmdDetail extends LlmdListItem {
  workspace_display_name: string; // 仅详情页用 (省列表页 N 次 GetItem)
  description?: string | null;
  k8s_namespace: string;
  k8s_name: string; // CR base 名 (= name); gateway svc = <k8s_name>-gateway, LWS = <k8s_name>-multi
  model_source_type: string;
  model_pvc: string;
  s3_bucket?: string | null;
  s3_prefix?: string | null;
  gateway_instance_type: string;
  launch_script: string;
  efa_per_pod: number;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  gateway_image: string;
  sglang_image: string;
  gateway_replicas: number;
  gateway_extra_args: string[];
  gateway_cpu_request_millicores: number;
  gateway_cpu_limit_millicores: number;
  gateway_memory_request_mib: number;
  gateway_memory_limit_mib: number;
  expose_alb: boolean;
  // ALB hostname, 一有地址就有值 (区分"ALB 就绪中"与"可调用")
  alb_dns?: string | null;
  labels: Record<string, string>;
  last_condition_message?: string | null;
  conditions: LlmdCondition[];
  pods: LlmdPodSummary[];
}
