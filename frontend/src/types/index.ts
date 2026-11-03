export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'stopped'
  | 'serving';

export type GpuType =
  | 'A100'
  | 'H100'
  | 'g5.8xlarge'
  | 'g5.12xlarge'
  | 'p5.48xlarge';

export type Framework =
  | 'pytorch'
  | 'tensorflow'
  | 'vllm'
  | 'sglang'
  | 'trtllm';

export interface Workspace {
  id: string;
  name: string;
  displayName: string;
  namespace: string;
  createdAt: string;
  quotaGpu: number;
  usedGpu: number;
  memberCount: number;
}

/**
 * 当前登录用户. 字段对齐后端 `/api/v1/users/me` (UserResponse).
 * id = IdC username (token identities[0].userId).
 * is_admin = PlatformAdmins 表里是否存在该 username.
 */
export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
}

export interface DevInstance {
  id: string;
  workspaceId: string;
  name: string;
  status: JobStatus;
  gpuType: GpuType;
  gpuCount: number;
  creator: string;
  createdAt: string;
  image: string;
  fsxMounts: string[];
  sshReady: boolean;
}

export interface TrainingJob {
  id: string;
  workspaceId: string;
  experimentId?: string;
  name: string;
  status: JobStatus;
  gpuType: GpuType;
  gpuCount: number;
  nodeCount: number;
  creator: string;
  createdAt: string;
  startedAt?: string;
  endedAt?: string;
  framework: Framework;
  image: string;
  command: string;
  currentStep?: number;
  totalSteps?: number;
  currentLoss?: number;
}

export interface InferenceService {
  id: string;
  workspaceId: string;
  name: string;
  status: JobStatus;
  framework: 'vllm' | 'sglang' | 'trtllm';
  modelRef: string;
  gpuType: GpuType;
  gpuCount: number;
  replicas: number;
  endpointUrl: string;
  qps?: number;
  ttftMs?: number;
}

export interface Experiment {
  id: string;
  workspaceId: string;
  name: string;
  tags: string[];
  runCount: number;
  createdAt: string;
}

export interface TimeSeriesPoint {
  /** Unix timestamp in milliseconds */
  timestamp: number;
  value: number;
}

/** ECharts tuple form: [timestamp, value] */
export type EChartsSeriesPoint = [number, number];
