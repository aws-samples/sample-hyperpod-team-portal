/**
 * llm-d API · wraps /workspaces/{id}/llmd + /llmd/{id} (分支B)
 */
import { apiFetch } from '@/shared/api';
import type {
  LlmdCreatePayload,
  LlmdDetail,
  LlmdListItem,
  LlmdPhase,
  LlmdScope,
} from './types';

export function listLlmd(
  wsId: string,
  params?: { scope?: LlmdScope; phase?: LlmdPhase },
): Promise<LlmdListItem[]> {
  const qs = new URLSearchParams();
  if (params?.scope) qs.set('scope', params.scope);
  if (params?.phase) qs.set('phase', params.phase);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<LlmdListItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/llmd${suffix}`,
  );
}

export function createLlmd(
  wsId: string,
  payload: LlmdCreatePayload,
): Promise<LlmdDetail> {
  return apiFetch<LlmdDetail>(`/workspaces/${encodeURIComponent(wsId)}/llmd`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function previewLlmd(
  wsId: string,
  payload: LlmdCreatePayload,
): Promise<{ yaml: string }> {
  return apiFetch<{ yaml: string }>(
    `/workspaces/${encodeURIComponent(wsId)}/llmd/preview`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function getLlmd(
  id: string,
  params?: { sync?: boolean },
): Promise<LlmdDetail> {
  const qs = new URLSearchParams();
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<LlmdDetail>(`/llmd/${encodeURIComponent(id)}${suffix}`);
}

export function stopLlmd(id: string): Promise<LlmdDetail> {
  return apiFetch<LlmdDetail>(`/llmd/${encodeURIComponent(id)}/stop`, {
    method: 'POST',
  });
}

export function deleteLlmd(id: string): Promise<void> {
  return apiFetch<void>(`/llmd/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function getLlmdKueueDetail(
  id: string,
  workloadName: string,
): Promise<import('@/shared/kueue').KueueDetail> {
  return apiFetch(
    `/llmd/${encodeURIComponent(id)}/kueue-detail?workload=${encodeURIComponent(workloadName)}`,
  );
}
