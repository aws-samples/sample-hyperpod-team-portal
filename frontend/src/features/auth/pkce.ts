/**
 * PKCE (Proof Key for Code Exchange · RFC 7636) 工具.
 *
 * 流程:
 * 1. 跳 Cognito 前: 生成 code_verifier (随机串) + code_challenge (S256 hash)
 * 2. 把 verifier + state 存 sessionStorage, challenge 跟着 authorize 请求送 Cognito
 * 3. callback 回来后, 用 code + verifier 换 token
 * 4. Cognito 验 sha256(verifier) === challenge, 防止 code 被中间人截获
 *
 * 为什么 SPA 必须用 PKCE: SPA 没有 client_secret (代码在浏览器里, 藏不住),
 * 没法用传统的 client_secret 在 token endpoint 鉴权. PKCE 用一对随机串
 * 替代 secret 的角色, 而且 verifier 从不出网络, 防中间人有效.
 */

const VERIFIER_KEY = 'auth_pkce_verifier';
const STATE_KEY = 'auth_pkce_state';

/** 生成 RFC 7636 §4.1 的 code_verifier · 43-128 字符 [A-Za-z0-9-._~] */
export function generateCodeVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

/** 生成 code_challenge · SHA-256(verifier) 后 base64url */
export async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(hashBuffer));
}

/** 生成防 CSRF 的 state · 跟 verifier 一起存 sessionStorage, callback 校验 */
export function generateState(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

export function saveVerifierAndState(verifier: string, state: string): void {
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
}

/** 取出 verifier + state 后立即从 sessionStorage 删除 (一次性使用). */
export function popVerifierAndState(): {
  verifier: string | null;
  state: string | null;
} {
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  const state = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  return { verifier, state };
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
