/**
 * Dev Instance API — wraps /dev-instance-templates + /dev-instances endpoints.
 */
import { apiFetch } from '@/shared/api';
import type {
  AccessInfo,
  AuthorizedKeyResult,
  DevInstanceCreatePayload,
  DevInstanceDetail,
  DevInstanceListItem,
  DevInstanceResizePayload,
  DevInstanceUpdatePayload,
  SharedPVCInfo,
  TemplateInfo,
} from './types';

export * from './types';

export function listTemplates(): Promise<TemplateInfo[]> {
  return apiFetch<TemplateInfo[]>('/dev-instance-templates');
}

export function listSharedPVCs(wsId: string): Promise<SharedPVCInfo[]> {
  return apiFetch<SharedPVCInfo[]>(
    `/workspaces/${encodeURIComponent(wsId)}/shared-pvcs`,
  );
}

export function listDevInstances(wsId: string): Promise<DevInstanceListItem[]> {
  return apiFetch<DevInstanceListItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/dev-instances`,
  );
}

export function getDevInstance(id: string): Promise<DevInstanceDetail> {
  return apiFetch<DevInstanceDetail>(`/dev-instances/${encodeURIComponent(id)}`);
}

export function createDevInstance(
  wsId: string,
  payload: DevInstanceCreatePayload,
): Promise<DevInstanceDetail> {
  return apiFetch<DevInstanceDetail>(
    `/workspaces/${encodeURIComponent(wsId)}/dev-instances`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function updateDevInstance(
  id: string,
  payload: DevInstanceUpdatePayload,
): Promise<DevInstanceDetail> {
  return apiFetch<DevInstanceDetail>(`/dev-instances/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function resizeDevInstance(
  id: string,
  payload: DevInstanceResizePayload,
): Promise<DevInstanceDetail> {
  return apiFetch<DevInstanceDetail>(
    `/dev-instances/${encodeURIComponent(id)}/resize`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  );
}

export function stopDevInstance(id: string): Promise<DevInstanceDetail> {
  return apiFetch<DevInstanceDetail>(
    `/dev-instances/${encodeURIComponent(id)}/stop`,
    { method: 'POST' },
  );
}

export function startDevInstance(id: string): Promise<DevInstanceDetail> {
  return apiFetch<DevInstanceDetail>(
    `/dev-instances/${encodeURIComponent(id)}/start`,
    { method: 'POST' },
  );
}

export function deleteDevInstance(id: string): Promise<void> {
  return apiFetch<void>(`/dev-instances/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function getAccessInfo(id: string): Promise<AccessInfo> {
  return apiFetch<AccessInfo>(
    `/dev-instances/${encodeURIComponent(id)}/access-info`,
  );
}

/** 把用户 SSH 公钥写入开发机 ~/.ssh/authorized_keys (平台代跑, 免手动进终端粘命令)。 */
export function addAuthorizedKey(
  id: string,
  publicKey: string,
): Promise<AuthorizedKeyResult> {
  return apiFetch<AuthorizedKeyResult>(
    `/dev-instances/${encodeURIComponent(id)}/authorized-keys`,
    { method: 'POST', body: JSON.stringify({ public_key: publicKey }) },
  );
}

export function getDevInstanceStatusDetail(
  id: string,
): Promise<{ status_detail: unknown }> {
  return apiFetch<{ status_detail: unknown }>(
    `/dev-instances/${encodeURIComponent(id)}/status-detail`,
  );
}

export function getDevInstanceKueueDetail(
  id: string,
): Promise<import('@/shared/kueue').KueueDetail> {
  return apiFetch(
    `/dev-instances/${encodeURIComponent(id)}/kueue-detail`,
  );
}

/**
 * 拼浏览器打开 JupyterLab/Code Editor 的 proxy URL.
 * 后端 /proxy/* 转发到主容器 :8888.
 *
 * - 生产 ALB authenticate-cognito 后, window.open 带 ELB session cookie,
 *   后端 auth_middleware ALB 路径校验通过, 不需要 query token.
 * - 本地 mac 调试时若启用 enable_dev_proxy_query_token, 这里把 ID token
 *   拼到 ?access_token= (生产环境此 env 关闭, 这段不生效, 但也不冲突).
 *
 * NOTE: JupyterLab 302-redirects when the trailing slash is missing — always keep it.
 */
export function buildProxyUrl(id: string, path = ''): string {
  const clean = path.replace(/^\/+/, '');
  const base = `/api/v1/dev-instances/${encodeURIComponent(id)}/proxy/${clean}`;
  let token: string | null = null;
  try {
    token = localStorage.getItem('auth_id_token');
  } catch {
    /* SSR / privacy mode */
  }
  if (!token) return base;
  const sep = base.includes('?') ? '&' : '?';
  return `${base}${sep}access_token=${encodeURIComponent(token)}`;
}
