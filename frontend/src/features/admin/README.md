# features/admin

管理员控制台 feature —— 10 页管理员视图（平台层、非 workspace 作用域）。

## Domain 边界

仅覆盖"平台管理员"身份能看到的全局资源 CRUD / 查询：

- Dashboard / Cluster / ResourcePools / Nodes（集群与计算）
- Scheduling / Quota（调度与配额治理）
- Storage / FsxPermission（文件系统 + 权限组，FsxPermission 是 legacy 重定向 shim）
- Network / Events / Audit（可观测与合规）

## 页面清单

| page                  | 路由                            | 备注                                       |
| --------------------- | ------------------------------- | ------------------------------------------ |
| `Dashboard.tsx`       | `/admin/dashboard`              | 平台总览                                   |
| `Cluster.tsx`         | `/admin/cluster`                | 集群列表 + 摘要 + sync + 团队配额联动      |
| `ResourcePools.tsx`   | `/admin/resource-pools`         |                                            |
| `Nodes.tsx`           | `/admin/nodes`                  |                                            |
| `Scheduling.tsx`      | `/admin/scheduling`             | Kueue 调度队列                             |
| `Quota.tsx`           | `/admin/quota`                  | Legacy shim，引导到 Cluster 页内 Tab       |
| `Storage.tsx`         | `/admin/storage`                | 3-tab：文件系统 / 权限组 / 数据集          |
| `FsxPermission.tsx`   | `/admin/fsx-permission`         | Navigate shim → `/admin/storage?tab=...`   |
| `Network.tsx`         | `/admin/network`                |                                            |
| `Events.tsx`          | `/admin/events`                 |                                            |
| `Audit.tsx`           | `/admin/audit`                  |                                            |

## 上游依赖

- `@/shared/api` — `apiFetch` / `ApiError`
- `@/features/quota/api` — 配额 API（由 quota feature 持有，C3 迁移）
- `@/api/workspace` — listWorkspaces（未迁到 workspace feature 前暂保持）
- `@/components/metrics/chartTheme` — ECharts 色板（Wave 3 后续迁 `@/shared/ui/charts`）
- `@/mock/*` — prototype 阶段的 mock 数据
- `@/store` — 当前 workspace / user

## 下游消费者

- `@/router` —— 路由入口
- 其他 feature **不得** 直接 import admin 页面组件。若需要共享类型或 helpers，在 `index.ts` 显式导出。

## API

admin feature **自己**持有 `cluster` API（平台视角 GET /clusters /
sync）。`quota` 由 quota feature 持有，admin 通过 `@/features/quota/api`
引用 —— 同时为了保持 admin 内部"就近一致"的习惯，本目录也导出了
`api/quota.ts` 作为对 quota feature 的再导出 barrel。

- `api/cluster.ts` —— `listClusters` / `getClusterSummary` / `syncCluster`
- `api/quota.ts` —— re-export of `@/features/quota/api`
