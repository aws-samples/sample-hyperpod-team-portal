/**
 * llm-d feature (多机推理, 分支B: LWS + sgl-model-gateway) — public exports.
 *
 * 与 dynamo feature 物理隔离, 各查各的 resource_type。Router 从这里 import,
 * 勿伸进 subpath (破坏 feature 边界)。
 */

// Pages (consumed by router)
export { default as LlmdList } from './pages/List';
export { default as LlmdCreate } from './pages/Create';
export { default as LlmdDetail } from './pages/Detail';

// API surface
export {
  createLlmd,
  deleteLlmd,
  getLlmd,
  listLlmd,
  previewLlmd,
  stopLlmd,
} from './api/client';
export type {
  LlmdCondition,
  LlmdCreatePayload,
  LlmdDetail as LlmdDetailType,
  LlmdListItem,
  LlmdPhase,
  LlmdPodSummary,
  LlmdScope,
} from './api/types';
