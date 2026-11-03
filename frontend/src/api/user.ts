/**
 * User API — wraps /users list + /users/me + /users/{id}.
 *
 * @deprecated Wave 5 P0-4 — 暂保留 (user feature 尚未拆出),
 * 建立 features/user/api/ 后请把内容迁过去并删本文件.
 */
import { apiFetch } from '@/shared/api';

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface CurrentUser extends User {
  // M1 no auth → backend returns a default seed user. Roles etc. deferred to M2.
  roles?: string[];
}

function buildQuery(params?: Record<string, string | undefined>): string {
  if (!params) return '';
  const pairs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `?${pairs.join('&')}` : '';
}

export function listUsers(q?: string): Promise<User[]> {
  return apiFetch<User[]>(`/users${buildQuery({ q })}`);
}

export function getCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>('/users/me');
}

export function getUser(id: string): Promise<User> {
  return apiFetch<User>(`/users/${encodeURIComponent(id)}`);
}

// ===== IdC user search (admin 加 ws 成员时用) =====

/** IdC 搜索响应 · 后端走 GetUserId + DescribeUser, 精确等值. 0 或 1 条. */
export interface IdcUserSummary {
  username: string;
  email: string;
  display_name: string;
}

/**
 * 搜索 IdC 用户. q 是完整 username 或 完整 email (含 @ 视作 email).
 * 不支持 prefix/contains, admin 必须输完整字符串.
 *
 * 仅 platform admin 可调.
 */
export function searchIdcUsers(q: string): Promise<IdcUserSummary[]> {
  return apiFetch<IdcUserSummary[]>(
    `/idc/users?q=${encodeURIComponent(q)}`,
  );
}
