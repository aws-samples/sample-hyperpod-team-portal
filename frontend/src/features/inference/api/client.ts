/**
 * Inference API · wraps /workspaces/{id}/inferences + /inferences/{id}
 */
import { apiFetch } from '@/shared/api';
import type {
  InferenceCreatePayload,
  InferenceDetail,
  InferenceListItem,
  InferencePhase,
  InferenceScope,
} from './types';

export function listInferences(
  wsId: string,
  params?: { scope?: InferenceScope; phase?: InferencePhase; sync?: boolean },
): Promise<InferenceListItem[]> {
  const qs = new URLSearchParams();
  if (params?.scope) qs.set('scope', params.scope);
  if (params?.phase) qs.set('phase', params.phase);
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<InferenceListItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/inferences${suffix}`,
  );
}

export function createInference(
  wsId: string,
  payload: InferenceCreatePayload,
): Promise<InferenceDetail> {
  return apiFetch<InferenceDetail>(
    `/workspaces/${encodeURIComponent(wsId)}/inferences`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function previewInference(
  wsId: string,
  payload: InferenceCreatePayload,
): Promise<{ yaml: string }> {
  return apiFetch<{ yaml: string }>(
    `/workspaces/${encodeURIComponent(wsId)}/inferences/preview`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function getInference(
  id: string,
  params?: { sync?: boolean },
): Promise<InferenceDetail> {
  const qs = new URLSearchParams();
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<InferenceDetail>(
    `/inferences/${encodeURIComponent(id)}${suffix}`,
  );
}

export function stopInference(id: string): Promise<InferenceDetail> {
  return apiFetch<InferenceDetail>(
    `/inferences/${encodeURIComponent(id)}/stop`,
    { method: 'POST' },
  );
}

export function deleteInference(id: string): Promise<void> {
  return apiFetch<void>(`/inferences/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function getInferenceStatusDetail(
  id: string,
): Promise<{ status_detail: unknown }> {
  return apiFetch<{ status_detail: unknown }>(
    `/inferences/${encodeURIComponent(id)}/status-detail`,
  );
}

export function getInferenceKueueDetail(
  id: string,
): Promise<import('@/shared/kueue').KueueDetail> {
  return apiFetch(
    `/inferences/${encodeURIComponent(id)}/kueue-detail`,
  );
}

export function getInferenceKueueDetailByWorkload(
  id: string,
  workloadName: string,
): Promise<import('@/shared/kueue').KueueDetail> {
  return apiFetch(
    `/inferences/${encodeURIComponent(id)}/kueue-detail-by-workload?workload=${encodeURIComponent(workloadName)}`,
  );
}
