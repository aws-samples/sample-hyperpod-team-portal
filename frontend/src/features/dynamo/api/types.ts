/**
 * Dynamo (多机推理) TS types · 镜像 backend app/modules/dynamo/api/schemas.py
 *
 * 对齐推理服务: 模型走授权 FSx/S3 挂载源 (后端授权反查 pvc), tp/ep/model-path 进启动脚本;
 * 资源走资源模板 (锁单节点 gpu/cpu/mem/efa) × node_count。
 */

export type DynamoBackend = 'sglang';

export type DynamoModelSourceType = 'fsx' | 's3';

// status.state (Go controller derive_dynamo 写); Stopped 是平台哨兵
export type DynamoPhase =
  | 'initializing'
  | 'pending'
  | 'successful'
  | 'failed'
  | 'Stopped';

export type DynamoScope = 'mine' | 'all';

export interface DynamoS3Source {
  bucket_name: string;
  region: string;
  model_location: string;
  prefetch_enabled: boolean;
}

export interface DynamoCreatePayload {
  name: string;
  display_name: string;
  description?: string | null;

  backend_framework: DynamoBackend;
  image: string;

  // 模型来源 (授权挂载源, 后端反查真值; 照训练/推理)
  model_source_type: DynamoModelSourceType;
  // FSx: 选中的授权挂载源 pvc_name (后端反查 mount_path + gid)
  fsx_pvc_name?: string | null;
  // S3: 挂载源反查出的 bucket/region + 用户填相对路径
  s3?: DynamoS3Source | null;

  // 多机: 节点数 (multinode.nodeCount, CR 字段); tp/ep/model-path 在启动脚本
  node_count: number;
  // 副本数 (worker.replicas): 几个独立实例数据并行; 总 pod = replicas × node_count
  replicas: number;
  // 启动脚本 (含 python3 -m dynamo.sglang --model-path ... --tp-size ... --ep-size ...)
  launch_script: string;

  // 资源 (来自资源模板, 锁单节点规格)
  instance_type: string;
  gpu_per_worker: number;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  efa_per_worker: number;

  // FSx 权限 (dynamo 镜像 uid=1000 读不了 FSx → root 跑通; 生产改 gid)
  run_as_root: boolean;

  labels: Record<string, string>;
}

export interface DynamoListItem {
  id: string;
  workspace_id: string;
  creator_user_id: string;
  creator_display_name: string;
  name: string;
  display_name: string;
  backend_framework: string;
  phase: DynamoPhase | string;
  kueue_status?: string | null;
  node_count: number;
  replicas: number;
  instance_type: string;
  gpu_per_worker: number;
  endpoint_url?: string | null;
  created_at: string;
  last_sync_at?: string | null;
}

export interface DynamoCondition {
  type?: string;
  status?: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

export interface DynamoContainerSummary {
  name?: string;
  ready?: boolean;
  status?: string;
  restarts?: number;
  reason?: string | null;
}

export interface DynamoPodSummary {
  name?: string;
  phase?: string;
  ready?: string;
  status?: string;
  restarts?: number;
  reason?: string | null;
  containers?: DynamoContainerSummary[];
  node_name?: string;
  pod_ip?: string;
  host_ip?: string;
  start_time?: string;
}

export interface DynamoDetail extends DynamoListItem {
  workspace_display_name: string; // 仅详情页用; 列表页不用故不放 ListItem (省 N 次 GetItem)
  description?: string | null;
  k8s_namespace: string;
  k8s_cr_name: string; // ★ pod 定位锚点 (= CR 名)
  image: string;
  model_source_type: string;
  fsx_pvc_name?: string | null;
  fsx_mount_path?: string | null;
  s3?: DynamoS3Source | null;
  launch_script?: string | null;
  cpu_request_millicores: number;
  cpu_limit_millicores: number;
  memory_request_mib: number;
  memory_limit_mib: number;
  efa_per_worker: number;
  run_as_root: boolean;
  labels: Record<string, string>;
  last_condition_message?: string | null;
  conditions: DynamoCondition[];
  pods: DynamoPodSummary[];
}
