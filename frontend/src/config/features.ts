// 临时隐藏未开放功能 (菜单入口)。放开: 从 HIDDEN_FEATURE_SEGMENTS 删对应项即可。
// 仅藏入口, 路由/页面保留 (直输 URL 仍可内部验证)。

/** 路由尾段, 命中则该功能菜单入口隐藏。 */
export const HIDDEN_FEATURE_SEGMENTS: readonly string[] = [
  'dynamo', // 多机推理
  // 'llmd', // llm-d 推理
];

/** path 末段是否命中隐藏名单 (menu path 形如 `/workspaces/:id/dynamo`)。 */
export const isHiddenFeaturePath = (path?: string): boolean => {
  if (!path) return false;
  const seg = path.split('/').pop() ?? '';
  return HIDDEN_FEATURE_SEGMENTS.includes(seg);
};
