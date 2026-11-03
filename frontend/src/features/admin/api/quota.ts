/**
 * Admin quota API — re-exports from `@/features/quota/api`.
 *
 * Wave 3 (C3) designated `features/quota` as the canonical owner of the
 * AWS ComputeQuota client + shared QuotaPreviewBar UI. Admin pages import
 * this local path so they stay feature-conventional while sharing the same
 * source of truth.
 */
export * from '@/features/quota/api';
