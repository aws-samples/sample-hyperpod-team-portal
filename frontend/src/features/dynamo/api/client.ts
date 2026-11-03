/**
 * Dynamo API · wraps /workspaces/{id}/dynamo-inferences + /dynamo-inferences/{id}
 */
import { apiFetch } from '@/shared/api';
import type {
  DynamoCreatePayload,
  DynamoDetail,
  DynamoListItem,
  DynamoPhase,
  DynamoScope,
} from './types';

export function listDynamo(
  wsId: string,
  params?: { scope?: DynamoScope; phase?: DynamoPhase },
): Promise<DynamoListItem[]> {
  const qs = new URLSearchParams();
  if (params?.scope) qs.set('scope', params.scope);
  if (params?.phase) qs.set('phase', params.phase);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<DynamoListItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/dynamo-inferences${suffix}`,
  );
}

export function createDynamo(
  wsId: string,
  payload: DynamoCreatePayload,
): Promise<DynamoDetail> {
  return apiFetch<DynamoDetail>(
    `/workspaces/${encodeURIComponent(wsId)}/dynamo-inferences`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function previewDynamo(
  wsId: string,
  payload: DynamoCreatePayload,
): Promise<{ yaml: string }> {
  return apiFetch<{ yaml: string }>(
    `/workspaces/${encodeURIComponent(wsId)}/dynamo-inferences/preview`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function getDynamo(
  id: string,
  params?: { sync?: boolean },
): Promise<DynamoDetail> {
  const qs = new URLSearchParams();
  if (params?.sync) qs.set('sync', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<DynamoDetail>(
    `/dynamo-inferences/${encodeURIComponent(id)}${suffix}`,
  );
}

export function getDynamoStatusDetail(
  id: string,
): Promise<{ status_detail: unknown }> {
  return apiFetch<{ status_detail: unknown }>(
    `/dynamo-inferences/${encodeURIComponent(id)}/status-detail`,
  );
}

export function stopDynamo(id: string): Promise<DynamoDetail> {
  return apiFetch<DynamoDetail>(
    `/dynamo-inferences/${encodeURIComponent(id)}/stop`,
    { method: 'POST' },
  );
}

export function deleteDynamo(id: string): Promise<void> {
  return apiFetch<void>(`/dynamo-inferences/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}
