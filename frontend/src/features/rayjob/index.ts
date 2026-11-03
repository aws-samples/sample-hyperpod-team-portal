/**
 * RayJob feature (Ray 训练) — public exports.
 *
 * 与训练任务 UI 平级, 独立 feature (各查各的 resource_type)。Router 从这里 import,
 * 勿伸进 subpath (破坏 feature 边界)。
 */

// Pages (consumed by router)
export { default as RayJobList } from './pages/List';
export { default as RayJobCreate } from './pages/Create';
export { default as RayJobDetail } from './pages/Detail';

// API surface
export {
  createRayJob,
  deleteRayJob,
  getRayJob,
  listRayJob,
  previewRayJob,
  stopRayJob,
} from './api/client';
export type {
  RayJobCreatePayload,
  RayJobDetail as RayJobDetailType,
  RayJobListItem,
  RayJobPhase,
  RayJobPodSummary,
  RayJobScope,
} from './api/types';
