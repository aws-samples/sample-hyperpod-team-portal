/**
 * Task overview API — wraps GET /workspaces/{id}/tasks (全 workspace 只读总览)。
 * 总览恒只返活跃任务 (后端 active_only); 前端做 filter/搜索/排序/分页。
 */
import { apiFetch } from '@/shared/api';
import type { QueueEntry, TaskOverviewResponse } from './types';

// 列优先级档 / 改单任务优先级 复用 priority 模块 client (@/api/priority):
// listPriorityClasses() + patchTaskPriority(wsId, crName, name) — 后端
// priority 模块 (含 patch CR label + delete Workload 重建)。本文件只留总览页 API。
export function getTaskOverview(wsId: string): Promise<TaskOverviewResponse> {
  return apiFetch<TaskOverviewResponse>(
    `/workspaces/${encodeURIComponent(wsId)}/tasks`,
  );
}

/**
 * 排队任务的 Kueue LocalQueue 信息 {cr_name: {position, workloads}}。
 * position=min 身位 (0-based), workloads=全部调度单元明细 (升序)。
 * 实时查 Kueue visibility API; 查失败/不可达返 {} (静默降级)。
 */
export function getTaskQueueOrder(
  wsId: string,
): Promise<Record<string, QueueEntry>> {
  return apiFetch<Record<string, QueueEntry>>(
    `/workspaces/${encodeURIComponent(wsId)}/tasks/queue-order`,
  );
}
