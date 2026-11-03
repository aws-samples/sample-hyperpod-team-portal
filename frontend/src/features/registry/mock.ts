/**
 * 镜像中心 · 用途标签常量 + 小工具。
 *
 * 数据已接真实后端 (见 @/api/registry: listWorkspaceImages / registerWorkspaceImage /
 * unregisterWorkspaceImage), 本文件只保留 UI 展示用的常量与纯函数。
 */
import i18n from '@/shared/i18n';
import type { ImageUse } from '@/api/registry';

export type { ImageUse } from '@/api/registry';

/** 用途展示名: 渲染时调用 (不在模块顶层求值翻译文本)。 */
const IMAGE_USE_KEYS = {
  dev: 'use.dev',
  training: 'use.training',
  inference: 'use.inference',
} as const satisfies Record<ImageUse, string>;

export function imageUseLabel(use: ImageUse): string {
  return i18n.t(IMAGE_USE_KEYS[use], { ns: 'registry' });
}

/** 从 ECR URI 抽短名 (repo:tag 末段), 用户没填 display_name 时兜底展示。 */
export function shortNameFromUri(uri: string): string {
  const afterSlash = uri.split('/').pop() ?? uri;
  return afterSlash;
}
