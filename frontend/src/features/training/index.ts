/**
 * Training feature — public exports.
 *
 * Router and other features import from `@/features/training`. Never
 * reach into subpaths like `@/features/training/components/...` — that
 * breaks the feature isolation boundary.
 */

// Pages (consumed by router)
export { default as TrainingList } from './pages/List';
export { default as TrainingCreate } from './pages/Create';
export { default as TrainingDetail } from './pages/Detail';

// API surface (some callers outside training may need the types; keep minimal)
export {
  createTrainingJob,
  deleteTrainingJob,
  getTrainingJob,
  listTrainingJobs,
} from './api/client';
export type {
  TrainingCondition,
  TrainingJobCreatePayload,
  TrainingJobDetail,
  TrainingJobListItem,
  TrainingPhase,
  TrainingPodSummary,
  TrainingScope,
} from './api/types';
