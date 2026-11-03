/**
 * Barrel for the shared HTTP client. Prefer importing from `@/shared/api`
 * in new code; legacy modules that still say `from './client'` inside
 * `src/api/*.ts` will follow during Wave 3.
 */
export { apiFetch, ApiError } from './client';
