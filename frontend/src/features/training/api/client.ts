/**
 * Training jobs API — wraps /workspaces/{id}/training-jobs + /training-jobs/{id}.
 */
import { apiFetch } from '@/shared/api';
import type {
  TopologyLevel,
  TrainingJobCreatePayload,
  TrainingJobDetail,
  TrainingJobListItem,
  TrainingPhase,
  TrainingScope,
} from './types';

export function listTrainingJobs(
  wsId: string,
  params?: { scope?: TrainingScope; phase?: TrainingPhase; sync?: boolean },
): Promise<TrainingJobListItem[]> {
  const qs = new URLSearchParams();
  if (params?.scope) qs.set('scope', params.scope);
  if (params?.phase) qs.set('phase', params.phase);
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<TrainingJobListItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/training-jobs${suffix}`,
  );
}

export function createTrainingJob(
  wsId: string,
  payload: TrainingJobCreatePayload,
): Promise<TrainingJobDetail> {
  return apiFetch<TrainingJobDetail>(
    `/workspaces/${encodeURIComponent(wsId)}/training-jobs`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function previewTrainingJob(
  wsId: string,
  payload: TrainingJobCreatePayload,
): Promise<{ yaml: string }> {
  return apiFetch<{ yaml: string }>(
    `/workspaces/${encodeURIComponent(wsId)}/training-jobs/preview`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

/**
 * 该机型可用的拓扑层级 (由细到粗)。空数组 = 无可选层级 → 表单置灰。
 * 后端读集群真值 (ResourceFlavor → Topology), 不是硬编列表。
 */
export function getTopologyLevels(
  wsId: string,
  instanceType: string,
): Promise<TopologyLevel[]> {
  return apiFetch<TopologyLevel[]>(
    `/workspaces/${encodeURIComponent(wsId)}/training-jobs/topology-levels` +
      `?instance_type=${encodeURIComponent(instanceType)}`,
  );
}

export function getTrainingJob(
  id: string,
  params?: { sync?: boolean },
): Promise<TrainingJobDetail> {
  const qs = new URLSearchParams();
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<TrainingJobDetail>(
    `/training-jobs/${encodeURIComponent(id)}${suffix}`,
  );
}

export function deleteTrainingJob(id: string): Promise<void> {
  return apiFetch<void>(`/training-jobs/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function stopTrainingJob(id: string): Promise<TrainingJobDetail> {
  return apiFetch<TrainingJobDetail>(
    `/training-jobs/${encodeURIComponent(id)}/stop`,
    { method: 'POST' },
  );
}

export function getTrainingStatusDetail(
  id: string,
): Promise<{ status_detail: unknown }> {
  return apiFetch<{ status_detail: unknown }>(
    `/training-jobs/${encodeURIComponent(id)}/status-detail`,
  );
}

export function getTrainingKueueDetail(
  id: string,
): Promise<import('@/shared/kueue').KueueDetail> {
  return apiFetch(
    `/training-jobs/${encodeURIComponent(id)}/kueue-detail`,
  );
}
