/**
 * Training feature — domain types.
 *
 * Backend contract: services/platform-api/app/modules/training/api/router.py
 * Payloads use snake_case (backend is PEP 8); no alias transformation.
 */

export type TrainingPhase =
  | 'Pending'
  | 'Running'
  | 'Succeeded'
  | 'Failed'
  | 'Suspended'
  | 'Deleted';

export interface TrainingJobListItem {
  id: string;
  workspace_id: string;
  creator_user_id: string;
  creator_display_name: string;
  name: string;
  display_name: string;
  phase: TrainingPhase;
  kueue_status?: string | null; // Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像)
  node_count: number;
  spares?: number | null;
  gpu_per_node: number;
  cpu_per_node_millicores: number;
  memory_per_node_mib: number;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  last_sync_at: string | null;
}

export interface TrainingPodSummary {
  name: string;
  phase: string | null;
  ready?: string;
  status?: string;
  restarts?: number;
  reason?: string | null; // 崩溃原文 (lastState.terminated.message), 正常时 null
  node_name: string | null;
  pod_ip: string | null;
  host_ip: string | null;
  start_time: string | null;
}

export interface TrainingCondition {
  type?: string;
  status?: string;
  message?: string;
  last_transition_time?: string;
  [k: string]: unknown;
}

export interface TrainingJobDetail extends TrainingJobListItem {
  description: string | null;
  efa_per_node?: number;
  k8s_namespace: string;
  k8s_job_name: string;
  image: string;
  command: string;
  last_condition_message: string | null;
  env: Record<string, string>;
  env_secrets?: EnvSecret[];  // secret 注入的 env (克隆回填)
  // 训练参数 (UI "运行配置"卡渲)
  instance_type?: string | null;  // 选的机型, 克隆回填用
  code?: CodeSource | null;
  fsx_pvc?: string | null;
  fsx_mount_path?: string | null;
  fsx_gid?: number | null;
  s3_datasets?: S3DatasetMount[];
  extra_fsx_mounts?: ExtraFsxMount[];
  experiment_id?: string | null;
  priority_class?: string | null;
  topology_mode?: string | null;
  topology_label?: string | null;
  // runPolicy: 4 结构化字段 (克隆没编辑过时用这几个重建 YAML) + override 原文
  clean_pod_policy?: string;
  ttl_seconds_after_finished?: number;
  active_deadline_seconds?: number | null;
  job_max_retry_count?: number;
  run_policy_override?: Record<string, unknown> | null;
  labels?: Record<string, string>;
  conditions: TrainingCondition[];
  pods: TrainingPodSummary[];
}

export interface CodeSourceFsx {
  source?: 'fsx';
  // 代码在 FSx (挂载点 /fsx) 下的相对子目录 (空=fsx 根). 仅记录位置, 不单独挂载.
  // 挂载靠顶层 fsx_pvc (整块挂 /fsx 可读写).
  code_sub_path?: string;
  entrypoint?: string | null;
}

// 代码源回归只 FSx (github clone 已废弃)。
export type CodeSource = CodeSourceFsx;

export interface EnvSecret {
  // 从 Secret 注入的 env (值不明文, 走 secretKeyRef); secret_ref 后端补。
  name: string;
  secret_key: string;
  secret_ref?: string;
}

export interface S3DatasetMount {
  bucket: string;
  prefix?: string;
  mount_path: string;
  pvc_name?: string;
}

/** 训练创建时引用 ws 已挂 S3 数据集 (只传 mount_id, 后端查真值)。 */
export interface S3DatasetRef {
  mount_id: string;
}

export interface ExtraFsxMount {
  pvc_name: string;
  mount_path: string;
  read_only: boolean;
}

/** 训练创建时引用该 user 被授权的 FSx (只传 pvc_name, 后端反查授权真值)。 */
export interface FsxMountRef {
  pvc_name: string;
}

export type TopologyMode = 'none' | 'preferred' | 'required';
/**
 * 层级名由集群 Topology CR 决定 (换集群/换机型都不同), 故不做联合类型白名单 —
 * 选项走 GET /workspaces/{ws}/training-jobs/topology-levels 动态拿。
 */
export type TopologyLabel = string;

/** 该机型可用的一个拓扑层级 (后端读 ResourceFlavor → Topology 得出, 由细到粗)。 */
export interface TopologyLevel {
  node_label: string;
  /** Topology.levels 里的声明位置 (1-based, 粗→细) */
  depth: number;
  display_name: string;
}

export interface TrainingJobCreatePayload {
  // 不含 name: 后端从 display_name 派生, 传了会 422; 真名从响应的 name 字段读。
  // display_name 须 DNS 合法: ^[a-z][a-z0-9-]{1,27}[a-z0-9]$
  display_name: string;
  description?: string;
  image: string;
  // string = 单串 (后端 bash -lc 跑 / 或 wrap); string[] = exec 数组 (原样进 YAML command)
  command: string | string[];
  node_count?: number;
  spares?: number;
  gpu_per_node?: number;
  efa_per_node?: number;
  cpu_per_node_millicores?: number;
  memory_per_node_mib?: number;
  env?: Record<string, string>;
  // 从 Secret 注入的环境变量 (值不明文)
  env_secrets?: EnvSecret[];
  // SOW: 实验绑定 (选填) + 优先级 (默 training-default)
  experiment_id?: string;
  priority_class?: string;
  // 实例类型: 选 ws 配额机型, 后端 CR 写 nodeSelector 锁机型调度到对应池
  instance_type?: string;
  // 代码源: fsx=仅记录位置 / github=init container clone 到 /code。
  // FSx/S3 挂载 (都传引用, 后端反查授权真值)。
  code?: CodeSource | null;
  // FSx 挂载: 只传 pvc_name 引用该 user 被授权的 FSx, 后端反查 mount_path/ro-rw/gid。
  fsx_mounts?: FsxMountRef[];
  s3_datasets?: S3DatasetRef[];
  // 拓扑感知调度 (Kueue TAS · 仅 p5+/trn 生效)
  topology_mode?: TopologyMode;
  topology_label?: TopologyLabel | null;
  // runPolicy 整段覆盖 · 用户 step6 编辑的裸 YAML, 前端 yaml.load 成对象传入。
  // null/缺 = 用平台默认; 非空 = 整段覆盖 (后端白名单 + 校验)。
  run_policy_override?: Record<string, unknown> | null;
  // 平台是否自动套 hyperpodrun。默认 false = command 原样下发 (用户自管, 透明)。
  auto_wrap?: boolean;
  labels?: Record<string, string>;
}

export type TrainingScope = 'mine' | 'all';
