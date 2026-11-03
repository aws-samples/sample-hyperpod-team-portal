/**
 * Monitoring API — wraps the Prometheus-compatible backend proxy.
 * Backend: services/platform-api/app/modules/monitoring/router.py.
 *
 * Response shape mirrors Prometheus HTTP API so any Prom-compatible
 * renderer can consume it without re-shaping.
 *
 * @deprecated Wave 5 P0-4 — 暂保留 (monitoring feature 尚未拆出),
 * 建立 features/monitoring/api/ 后请把内容迁过去并删本文件.
 */
import { apiFetch } from '@/shared/api';

export type PromSampleValue = [number, string]; // [unix_sec, value_string]

export interface PromRangeResult {
  metric: Record<string, string>;
  values: PromSampleValue[];
}

export interface PromInstantResult {
  metric: Record<string, string>;
  value: PromSampleValue;
}

export interface PromResponseData {
  resultType: 'matrix' | 'vector' | 'scalar' | 'string';
  result: PromRangeResult[] | PromInstantResult[];
}

export interface PromResponse {
  status: 'success' | 'error';
  data?: PromResponseData;
  error_type?: string;
  error?: string;
}

export type MetricDimension = 'job' | 'pod' | 'gpu_card' | 'card';

export interface QueryTemplate {
  key: string;
  title: string;
  unit: string;
  promql: string;
  description?: string | null;
  category:
    | 'gpu'
    | 'cpu'
    | 'memory'
    | 'disk'
    | 'network'
    | 'training'
    | 'inference'
    | 'status'
    | 'event'
    | 'mlflow'
    | 'efa'
    | 'fsx'
    | 'process'
    | 'sglang'
    | 'dynamo'
    | 'ray';
  dimension?: MetricDimension;
  /** 按请求语言本地化后的分组展示名 */
  group?: string | null;
  /** 分组稳定标识 (slug), 用于排序 / 折叠 key */
  group_key?: string | null;
}

export function listInferenceTemplates(
  inferenceId: string,
): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/inferences/${encodeURIComponent(inferenceId)}/monitoring/templates`,
  );
}

export function listDynamoTemplates(
  dynamoId: string,
): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/dynamo-inferences/${encodeURIComponent(dynamoId)}/monitoring/templates`,
  );
}

export function listLlmdTemplates(
  llmdId: string,
): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/llmd-inferences/${encodeURIComponent(llmdId)}/monitoring/templates`,
  );
}

export function listRayjobTemplates(
  rayjobId: string,
): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/rayjobs/${encodeURIComponent(rayjobId)}/monitoring/templates`,
  );
}

/** 队列/配额页表格一行: 一个 workspace 当前等待中的 workload 数。 */
export interface KueueQueueRow {
  workspace_id: string;
  workspace_name: string;
  cluster_queue: string;
  /** 正常排队, 等前面跑完即可 */
  active: number;
  /** 超配额或拓扑不满足, 等下去也进不来 —— 要改任务规格或加配额 */
  inadmissible: number;
}

/** 监控页「队列 / 配额」: 各 workspace 当前排队情况 (按 inadmissible 倒序)。 */
export function listKueueQueues(): Promise<KueueQueueRow[]> {
  return apiFetch<KueueQueueRow[]>('/monitoring/kueue-queues');
}

export function instantQuery(
  query: string,
  time?: number,
): Promise<PromResponse> {
  return apiFetch<PromResponse>('/monitoring/query', {
    method: 'POST',
    body: JSON.stringify({ query, time }),
  });
}

export function rangeQuery(
  query: string,
  start: number,
  end: number,
  step = 15,
): Promise<PromResponse> {
  return apiFetch<PromResponse>('/monitoring/query_range', {
    method: 'POST',
    body: JSON.stringify({ query, start, end, step }),
  });
}

export interface GpuUtilizationResponse {
  namespace: string;
  days: number;
  avg: PromSampleValue[];
  max: PromSampleValue[];
  count: PromSampleValue[]; // 占用 GPU 卡数时序
}

/** Workspace 占用 GPU 的 N 天利用率时序 (avg+max). 仅 ws 管理员/超管 (后端 assert_ws_admin); 非管理员返 403. */
export function getWorkspaceGpuUtilization(
  wsId: string,
  days = 7,
): Promise<GpuUtilizationResponse> {
  return apiFetch<GpuUtilizationResponse>(
    `/workspaces/${encodeURIComponent(wsId)}/gpu-utilization?days=${days}`,
  );
}

export function listTrainingTemplates(
  jobId: string,
): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/training-jobs/${encodeURIComponent(jobId)}/monitoring/templates`,
  );
}

export function listDevInstanceTemplates(
  devId: string,
): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/dev-instances/${encodeURIComponent(devId)}/monitoring/templates`,
  );
}

export function listDevInstanceKpi(devId: string): Promise<QueryTemplate[]> {
  return apiFetch<QueryTemplate[]>(
    `/dev-instances/${encodeURIComponent(devId)}/monitoring/kpi`,
  );
}
