/**
 * 启动 PKCE flow · 跳到 Cognito Hosted UI 让用户登 IdC.
 *
 * 同时也包含 fetchAuthConfig() — 拿后端的 Cognito 配置.
 * 后端配置统一掌握 (issuer/client_id/domain/callback URL) 是为了:
 * 1. 切环境时只改后端 .env, 前端代码不动
 * 2. 部署 Fargate 时前端打包产物可以多环境复用
 */
import { apiFetch } from '@/shared/api';
import i18n from '@/shared/i18n';
import {
  generateCodeChallenge,
  generateCodeVerifier,
  generateState,
  saveVerifierAndState,
} from './pkce';

export interface AuthConfig {
  cognito_issuer: string;
  cognito_client_id: string;
  cognito_domain: string; // 形如 xxx.auth.{region}.amazoncognito.com (不带 https://)
  local_callback_url: string; // 形如 http://localhost:5173/auth/callback
}

let _configCache: AuthConfig | null = null;

/**
 * 拉后端 /api/v1/auth/config 拿 Cognito 配置.
 *
 * ⚠️ 后端必须暴露这个 endpoint (无需认证). 当前主项目 backend/app/modules/auth/
 * 还没实现这个端点, PR 1 先 skeleton 化, 后续 PR 后端补上即可启用.
 */
export async function fetchAuthConfig(): Promise<AuthConfig> {
  if (_configCache) return _configCache;
  _configCache = await apiFetch<AuthConfig>('/auth/config');
  return _configCache;
}

/** 跳到 Cognito Hosted UI 启动 PKCE flow.
 *
 * Cognito Hosted UI URL 结构:
 *   https://<domain>/oauth2/authorize
 *     ?client_id=<client_id>
 *     &response_type=code
 *     &scope=openid+profile+email
 *     &redirect_uri=<callback>
 *     &state=<csrf>
 *     &code_challenge=<S256(verifier)>
 *     &code_challenge_method=S256
 *
 * PoC 阶段不带 identity_provider, 走 Cognito 原生用户池 (username+password).
 * 后续接 IdC 联邦时再加回 &identity_provider=IdentityCenter.
 */
export async function startLogin(): Promise<void> {
  const cfg = await fetchAuthConfig();
  if (!cfg.cognito_domain || !cfg.cognito_client_id) {
    throw new Error(i18n.t('login.cognitoNotConfigured', { ns: 'auth' }));
  }

  const verifier = generateCodeVerifier();
  const challenge = await generateCodeChallenge(verifier);
  const state = generateState();
  saveVerifierAndState(verifier, state);

  const authUrl = new URL(`https://${cfg.cognito_domain}/oauth2/authorize`);
  authUrl.searchParams.set('client_id', cfg.cognito_client_id);
  authUrl.searchParams.set('response_type', 'code');
  authUrl.searchParams.set('scope', 'openid profile email');
  authUrl.searchParams.set('redirect_uri', cfg.local_callback_url);
  authUrl.searchParams.set('state', state);
  authUrl.searchParams.set('code_challenge', challenge);
  authUrl.searchParams.set('code_challenge_method', 'S256');

  window.location.assign(authUrl.toString());
}

/** 仅测试用 · 重置内存缓存的配置. */
export function _resetAuthConfigCache(): void {
  _configCache = null;
}
