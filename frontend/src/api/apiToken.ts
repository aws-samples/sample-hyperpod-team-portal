/**
 * 个人 API Token API · headless 脚本到人。
 * 后端: /api/v1/users/me/api-token (GET/POST/DELETE)。每人一把。
 */
import { apiFetch } from '@/shared/api';

export interface ApiTokenStatus {
  exists: boolean;
  token_display?: string | null;  // hypd_aweb**************cdce
  created_at?: string | null;
  expires_at?: string | null;     // null = 永不过期
}

export interface ApiTokenCreateBody {
  expires_at?: string | null;
  never_expire: boolean;
}

export interface ApiTokenCreated {
  token: string;                  // 明文, 仅此一次
  token_display: string;
  created_at: string;
  expires_at?: string | null;
}

export function getMyApiToken(): Promise<ApiTokenStatus> {
  return apiFetch<ApiTokenStatus>('/users/me/api-token');
}

export function createMyApiToken(body: ApiTokenCreateBody): Promise<ApiTokenCreated> {
  return apiFetch<ApiTokenCreated>('/users/me/api-token', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function deleteMyApiToken(): Promise<void> {
  return apiFetch<void>('/users/me/api-token', { method: 'DELETE' });
}
