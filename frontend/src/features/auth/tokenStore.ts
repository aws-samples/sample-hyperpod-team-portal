/**
 * Token 持久化 · POC 用 localStorage (XSS 风险可接受).
 *
 * 存的是 Cognito ID token (RS256 JWT, 1h 有效).
 * 过期检测用 JWT exp claim, 不依赖 localStorage 时间戳.
 *
 * 安全注意: 生产应用如 XSS 风险高, 可考虑改用 sessionStorage (关 tab 即清),
 * 或用 httpOnly cookie + ALB authenticate-cognito (POC 走 PKCE 不走 cookie).
 */

const ID_TOKEN_KEY = 'auth_id_token';

export function saveIdToken(token: string): void {
  localStorage.setItem(ID_TOKEN_KEY, token);
}

export function getIdToken(): string | null {
  const token = localStorage.getItem(ID_TOKEN_KEY);
  if (!token) return null;
  if (isExpired(token)) {
    clearIdToken();
    return null;
  }
  return token;
}

export function clearIdToken(): void {
  localStorage.removeItem(ID_TOKEN_KEY);
}

/**
 * 解 JWT payload (不验签, 仅看 exp 字段是否过期).
 *
 * 这里"不验签"是因为前端没必要 — token 真正的验签在后端 (verify_cognito_jwt).
 * 前端只是为了知道"已知过期就别再发请求, 直接重新登录", 所以看 exp 即可.
 */
function isExpired(token: string): boolean {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return true;
    const payload = JSON.parse(
      atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')),
    );
    if (typeof payload.exp !== 'number') return true;
    // 留 30s 提前量, 防 token 在请求路上过期
    return payload.exp * 1000 < Date.now() + 30_000;
  } catch {
    return true;
  }
}
