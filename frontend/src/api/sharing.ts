import { apiFetch } from '@/shared/api';

export type ShareResType = 'dev' | 'train' | 'rayjob';

export interface ShareItem {
  res_type: string;
  res_id: string;
  target_username: string;
  shared_by: string;
  shared_at: string;
}

export interface ShareBody {
  res_type: ShareResType;
  res_id: string;
  target_usernames: string[];
}

export const listShares = (
  wsId: string,
  resType: ShareResType,
  resId: string,
): Promise<ShareItem[]> =>
  apiFetch(
    `/workspaces/${encodeURIComponent(wsId)}/shares/${resType}/${encodeURIComponent(resId)}`,
  );

export const shareResource = (
  wsId: string,
  body: ShareBody,
): Promise<ShareItem[]> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/shares`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const unshareResource = (
  wsId: string,
  resType: ShareResType,
  resId: string,
  username: string,
): Promise<void> =>
  apiFetch(
    `/workspaces/${encodeURIComponent(wsId)}/shares/${resType}/${encodeURIComponent(resId)}/users/${encodeURIComponent(username)}`,
    { method: 'DELETE' },
  );
