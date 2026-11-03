/**
 * Auth feature 公开出口.
 *
 * 三白名单 import 规则:
 *   - 跨 feature 必走 barrel: import { ... } from '@/features/auth'
 *   - feature 内部用相对路径 ./xxx
 */
export { startLogin, fetchAuthConfig, type AuthConfig } from './login';
export { handleCallback, type CallbackResult } from './callback';
export { saveIdToken, getIdToken, clearIdToken } from './tokenStore';
export { AuthGate } from './components/AuthGate';
export { default as Callback } from './components/Callback';
