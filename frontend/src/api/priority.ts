/**
 * 优先级管理 API · SageMaker scheduler 配置 (weight 0-100) + 抢占开关 + 改单任务优先级.
 * 优先级档位通过 SageMaker cluster policy 管理，description 为只读字段（由官方 WPC 对象携带）。
 */
import { apiFetch } from '@/shared/api';

export type PreemptionPolicy = 'Never' | 'LowerPriority';

export interface PriorityClassItem {
  name: string;
  value: number;
  description?: string | null;
  in_use_count: number;
}

export interface PriorityClassCreateBody {
  name: string;          // 裸名 (会生成 <name>-priority)
  value: number;         // weight 0-100
}

export interface PriorityClassUpdateBody {
  value?: number;        // weight 0-100
}

export interface PreemptionState {
  workspace_id: string;
  namespace: string;
  cluster_queue: string;
  within_cluster_queue: PreemptionPolicy;
}

export interface WorkloadItem {
  workload_name: string;
  owner_name?: string | null;
  owner_kind?: string | null;
  priority?: number | null;
  priority_class_name?: string | null;
  admitted: boolean;
  queue_name?: string | null;
}

// ---------- 档位 (WPC) ----------

export function listPriorityClasses(): Promise<PriorityClassItem[]> {
  return apiFetch<PriorityClassItem[]>('/priority-classes');
}

export function createPriorityClass(
  body: PriorityClassCreateBody,
): Promise<PriorityClassItem> {
  return apiFetch<PriorityClassItem>('/priority-classes', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function updatePriorityClass(
  name: string,
  body: PriorityClassUpdateBody,
): Promise<PriorityClassItem> {
  return apiFetch<PriorityClassItem>(`/priority-classes/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function deletePriorityClass(name: string): Promise<void> {
  return apiFetch<void>(`/priority-classes/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

// ---------- 抢占开关 (per-ws) ----------

export function getPreemption(wsId: string): Promise<PreemptionState> {
  return apiFetch<PreemptionState>(
    `/workspaces/${encodeURIComponent(wsId)}/preemption`,
  );
}

export function setPreemption(
  wsId: string,
  within: PreemptionPolicy,
): Promise<PreemptionState> {
  return apiFetch<PreemptionState>(
    `/workspaces/${encodeURIComponent(wsId)}/preemption`,
    { method: 'PUT', body: JSON.stringify({ within_cluster_queue: within }) },
  );
}

// ---------- 单任务优先级 (任务总览页 P5 用; 此处先备) ----------

export function listWorkloads(wsId: string): Promise<WorkloadItem[]> {
  return apiFetch<WorkloadItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/workloads`,
  );
}

export function patchTaskPriority(
  wsId: string,
  taskType: string,
  crName: string,
  priorityClassName: string,
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(
    `/workspaces/${encodeURIComponent(wsId)}/tasks/${encodeURIComponent(crName)}/priority`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        task_type: taskType,
        priority_class_name: priorityClassName,
      }),
    },
  );
}
