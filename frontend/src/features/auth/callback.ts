/**
 * Callback handler · Cognito 把用户 302 回 /auth/callback?code=XXX&state=YYY 后调它.
 *
 * 流程:
 * 1. 从 URL 拿 code + state
 * 2. 验 state (防 CSRF)
 * 3. 拿 sessionStorage 里的 verifier
 * 4. POST Cognito /oauth2/token 用 code + verifier 换 id_token
 * 5. 存 localStorage, 跳回首页
 */
import i18n from '@/shared/i18n';
import { fetchAuthConfig } from './login';
import { popVerifierAndState } from './pkce';
import { saveIdToken } from './tokenStore';

export interface CallbackResult {
  ok: boolean;
  error?: string;
}

export async function handleCallback(): Promise<CallbackResult> {
  const params = new URLSearchParams(window.location.search);

  // Cognito 失败时会带 error 参数 (用户拒绝授权 / SAML 错 / ...)
  const error = params.get('error');
  if (error) {
    const description = params.get('error_description') ?? '';
    return { ok: false, error: `${error}: ${description}` };
  }

  const code = params.get('code');
  const state = params.get('state');
  if (!code || !state) {
    return { ok: false, error: 'missing code or state in callback URL' };
  }

  const { verifier, state: savedState } = popVerifierAndState();
  if (!verifier || !savedState) {
    return {
      ok: false,
      error: i18n.t('callback.verifierMissing', { ns: 'auth' }),
    };
  }
  if (state !== savedState) {
    return { ok: false, error: i18n.t('callback.stateMismatch', { ns: 'auth' }) };
  }

  const cfg = await fetchAuthConfig();

  // 调 Cognito token endpoint 换 id_token
  // 注意: public client (没 client_secret) 不带 Authorization header
  const body = new URLSearchParams();
  body.set('grant_type', 'authorization_code');
  body.set('client_id', cfg.cognito_client_id);
  body.set('code', code);
  body.set('redirect_uri', cfg.local_callback_url);
  body.set('code_verifier', verifier);

  const tokenResp = await fetch(`https://${cfg.cognito_domain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });

  if (!tokenResp.ok) {
    const errBody = await tokenResp.text();
    return {
      ok: false,
      error: `Cognito token endpoint failed: HTTP ${tokenResp.status} ${errBody}`,
    };
  }

  const tokens = await tokenResp.json();
  if (!tokens.id_token) {
    return { ok: false, error: 'Cognito response missing id_token' };
  }

  saveIdToken(tokens.id_token);
  return { ok: true };
}
