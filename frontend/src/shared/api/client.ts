/**
 * Lightweight fetch wrapper for HyperPod platform-api.
 * No external deps (no axios / no tanstack-query) — keep the prototype footprint minimal.
 *
 * Wave 1 skeleton: this is the canonical location. Legacy `@/api/client`
 * now re-exports from here. Wave 3 will migrate feature API modules.
 *
 * Auth 集成 (PR feat/frontend-pkce-auth):
 * 自动从 features/auth/tokenStore 读 Cognito ID token, 加到 Authorization
 * header. localStorage 没 token 时不加, 行为与原来一致 (mock 模式 0 影响).
 */

import { currentLocale } from '@/shared/i18n';

// 默认空串 = 走相对路径 /api/v1/... → Vite dev proxy 转发到后端 (vite.config.ts)
// 生产部署 SPA 和后端同源 (ALB 后面), 相对路径同样直达后端, 无需改这里.
// 真要切别的 host (跨域调试 / 远程后端), 设 VITE_API_BASE_URL=http://other-host:8800
const DEFAULT_BASE = '';

const rawBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? DEFAULT_BASE;
// Strip trailing slash to keep path joining predictable.
const baseURL = rawBase.replace(/\/+$/, '');

// Lazy-import 防 features/auth ↔ shared/api 循环依赖 (auth 内部也可能用 apiFetch).
// 顶层 import './...' 一旦形成环, vite 会丢一些 export 变 undefined.
function readIdToken(): string | null {
  try {
    // 见 features/auth/tokenStore.ts: ID_TOKEN_KEY
    const token = localStorage.getItem('auth_id_token');
    return token || null;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;
  constructor(status: number, message: string, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${baseURL}/api/v1${path.startsWith('/') ? path : `/${path}`}`;
  const headers = new Headers(init?.headers);
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  // 显式带用户选中的语言 (覆盖浏览器自动带的系统语言), 后端据此本地化报错 / 提示 / 指标文案。
  if (!headers.has('Accept-Language')) headers.set('Accept-Language', currentLocale());
  // 自动附加 Cognito ID token (无 token 时不加, 与原行为一致)
  const token = readIdToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const resp = await fetch(url, {
    ...init,
    headers,
  });

  const text = await resp.text();
  const body = text ? safeJson(text) : null;

  if (!resp.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>)
        ? (body as Record<string, unknown>).detail
        : null;
    let msg: string;
    if (Array.isArray(detail)) {
      // FastAPI 422 validation error: list of {loc, msg, type}
      msg = detail
        .map((e: unknown) => {
          if (e && typeof e === 'object') {
            const obj = e as Record<string, unknown>;
            const loc = Array.isArray(obj.loc) ? obj.loc.join('.') : '';
            return `${loc}: ${obj.msg ?? JSON.stringify(obj)}`;
          }
          return String(e);
        })
        .join(' | ');
    } else if (typeof detail === 'string') {
      msg = detail;
    } else if (detail != null) {
      msg = JSON.stringify(detail);
    } else {
      msg = resp.statusText || `HTTP ${resp.status}`;
    }
    throw new ApiError(resp.status, msg, body);
  }
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
