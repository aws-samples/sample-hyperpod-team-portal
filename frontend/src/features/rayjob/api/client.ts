/**
 * RayJob API · wraps /workspaces/{id}/rayjobs + /rayjobs/{id}
 */
import { apiFetch } from '@/shared/api';
import type {
  RayJobCreatePayload,
  RayJobDetail,
  RayJobListItem,
  RayJobPhase,
  RayJobScope,
} from './types';

export function listRayJob(
  wsId: string,
  params?: { scope?: RayJobScope; phase?: RayJobPhase },
): Promise<RayJobListItem[]> {
  const qs = new URLSearchParams();
  if (params?.scope) qs.set('scope', params.scope);
  if (params?.phase) qs.set('phase', params.phase);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<RayJobListItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/rayjobs${suffix}`,
  );
}

export function createRayJob(
  wsId: string,
  payload: RayJobCreatePayload,
): Promise<RayJobDetail> {
  return apiFetch<RayJobDetail>(
    `/workspaces/${encodeURIComponent(wsId)}/rayjobs`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function previewRayJob(
  wsId: string,
  payload: RayJobCreatePayload,
): Promise<{ yaml: string }> {
  return apiFetch<{ yaml: string }>(
    `/workspaces/${encodeURIComponent(wsId)}/rayjobs/preview`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function getRayJob(
  id: string,
  params?: { sync?: boolean },
): Promise<RayJobDetail> {
  const qs = new URLSearchParams();
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<RayJobDetail>(`/rayjobs/${encodeURIComponent(id)}${suffix}`);
}

/** Ray driver 日志 (entrypoint 真输出, exec head cat job-driver-*.log)。 */
export function getRayJobDriverLogs(
  id: string,
  pod: string,
): Promise<{ text: string; found: boolean }> {
  return apiFetch<{ text: string; found: boolean }>(
    `/rayjobs/${encodeURIComponent(id)}/driver-logs?pod=${encodeURIComponent(pod)}`,
  );
}

/** status_detail 全量 JSON (Go controller 落库的 RayJob status 原始快照, debug 弹窗用)。 */
export function getRayJobStatusDetail(
  id: string,
): Promise<{ status_detail: unknown }> {
  return apiFetch<{ status_detail: unknown }>(
    `/rayjobs/${encodeURIComponent(id)}/status-detail`,
  );
}

/** 实时查该 Ray 任务背后的 Kueue Workload (conditions + admission), 不落库。 */
export function getRayJobKueueDetail(
  id: string,
): Promise<import('@/shared/kueue').KueueDetail> {
  return apiFetch(`/rayjobs/${encodeURIComponent(id)}/kueue-detail`);
}

export function stopRayJob(id: string): Promise<RayJobDetail> {
  return apiFetch<RayJobDetail>(`/rayjobs/${encodeURIComponent(id)}/stop`, {
    method: 'POST',
  });
}

export function deleteRayJob(id: string): Promise<void> {
  return apiFetch<void>(`/rayjobs/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}
