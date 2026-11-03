/**
 * Dynamo feature (多机推理) — public exports.
 *
 * 与 inference feature 物理隔离, 各查各的 resource_type。Router 从这里 import,
 * 勿伸进 subpath (破坏 feature 边界)。
 */

// Pages (consumed by router)
export { default as DynamoList } from './pages/List';
export { default as DynamoCreate } from './pages/Create';
export { default as DynamoDetail } from './pages/Detail';

// API surface
export {
  createDynamo,
  deleteDynamo,
  getDynamo,
  listDynamo,
  previewDynamo,
  stopDynamo,
} from './api/client';
export type {
  DynamoBackend,
  DynamoCondition,
  DynamoCreatePayload,
  DynamoDetail as DynamoDetailType,
  DynamoListItem,
  DynamoPhase,
  DynamoPodSummary,
  DynamoScope,
} from './api/types';
