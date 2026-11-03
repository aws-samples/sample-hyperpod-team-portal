/**
 * 通用 Secret API · 每人一把 key-value 凭证 (B2 方案).
 *
 * 后端: app/modules/secret/api/router.py
 * secret 名平台自动派生 (用户无感); 只管 key-value; value 建后不回显。
 */

import { apiFetch } from '@/shared/api';

export interface SecretView {
  keys: string[];
}

export const getSecretView = (wsId: string): Promise<SecretView> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/secrets`);

export const putSecretKey = (
  wsId: string,
  body: { key: string; value: string },
): Promise<SecretView> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/secrets/keys`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const deleteSecretKey = (wsId: string, key: string): Promise<SecretView> =>
  apiFetch(
    `/workspaces/${encodeURIComponent(wsId)}/secrets/keys/${encodeURIComponent(key)}`,
    { method: 'DELETE' },
  );
