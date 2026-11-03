/**
 * Inference feature — public exports.
 *
 * Router and other features import from `@/features/inference`. Never
 * reach into subpaths like `@/features/inference/components/...` — that
 * breaks the feature isolation boundary.
 */

// Pages (consumed by router)
export { default as InferenceList } from './pages/List';
export { default as InferenceCreate } from './pages/Create';
export { default as InferenceDetail } from './pages/Detail';

// API surface
export {
  createInference,
  deleteInference,
  getInference,
  listInferences,
} from './api/client';
export type {
  Framework,
  InferenceCondition,
  InferenceCreatePayload,
  InferenceDetail as InferenceDetailType,
  InferenceListItem,
  InferencePhase,
  InferencePodSummary,
  InferenceScope,
  L2CacheBackend,
  L2KvCacheConfig,
  ModelSourceFsx,
  ModelSourceHuggingFace,
  ModelSourceS3,
  ModelSourceType,
  RoutingStrategy,
} from './api/types';
