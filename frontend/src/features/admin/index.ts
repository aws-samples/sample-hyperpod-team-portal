/**
 * admin feature — 管理中心。本次设计仅保留两块:
 *   资源模版管理 (ResourceTemplates) + 优先级 label 管理 (PriorityLabels)。
 *
 * Consumers (router, cross-feature lookups) only import from this barrel;
 * internal layout of `pages/`, `components/`, `api/` stays private.
 *
 * 注: 旧管理页 (Dashboard/Cluster/Nodes/Scheduling/Storage/...) 文件暂留 pages/,
 * 但已不挂路由/菜单 (本次设计移除)。api/cluster 仍被 workspace/quota 复用, 保留。
 */

// Router-level pages (re-exported as named exports — each page file uses
// `export default`, so we alias the default here for clarity).
export { default as AdminResourceTemplates } from './pages/ResourceTemplates';
export { default as AdminPriorityLabels } from './pages/PriorityLabels';
export { default as AdminWorkspacePreemption } from './pages/WorkspacePreemption';
