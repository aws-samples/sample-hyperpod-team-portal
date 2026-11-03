/**
 * Dev-instance feature types.
 *
 * 唯一权威来源: ../../../shared/api/schema.gen.ts (由 `pnpm gen:api` 从后端
 * Pydantic schema 自动生成). 禁止在本文件手写与后端 schema 平行的 interface.
 *
 * 例外 (frontend-only types):
 * - 业务派生类型 (Pick / Omit / 联合)
 */

import type { components } from '@/shared/api/schema.gen';

type Schemas = components['schemas'];

// ===== 直接来自后端 (sole source of truth) =====
export type TemplateInfo = Schemas['TemplateInfo'];
export type DevInstanceListItem = Schemas['DevInstanceListItem'];
export type DevInstanceDetail = Schemas['DevInstanceDetail'];
export type AccessInfo = Schemas['AccessInfo'];
export type SharedPVCInfo = Schemas['SharedPVCInfo'];
export type VolumeMount = Schemas['VolumeMount'];
export type AuthorizedKeyResult = Schemas['AuthorizedKeyResult'];

// 创建/更新载荷 (与后端 schema 一致)
export type DevInstanceCreatePayload = Schemas['DevInstanceCreate'];
export type DevInstanceUpdatePayload = Schemas['DevInstanceUpdate'];
export type DevInstanceResizePayload = Schemas['DevInstanceResize'];

// ===== Frontend-only 派生类型 =====

/** desired_status (后端 enum 没有, 前端约定) */
export type DevInstanceDesiredStatus = 'Running' | 'Stopped' | string;

/** 兼容旧名 (创建表单还在用 VolumeMountPayload, 等 P0-4 收口) */
export type VolumeMountPayload = VolumeMount;

/** k8s condition 透传 (后端 list[dict[str,Any]], 前端补结构) */
export interface DevInstanceCondition {
  type: string;
  status: string;
  reason?: string | null;
  message?: string | null;
  lastTransitionTime?: string | null;
  [k: string]: unknown;
}
