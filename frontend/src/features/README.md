# features/

Feature-sliced layout for the HyperPod Platform prototype. Each subfolder
under `features/` owns **one** user-visible capability end-to-end — its
pages, its API calls, its local state, its local components, and its
domain types.

> Wave 1 status: **skeleton only**. No features have been migrated yet.

## 目标 feature 清单（Wave 3）

每个 feature 对应用户认知中的一块独立业务领域：

| feature          | 对应旧 pages             | 对应旧 api                | 备注                         |
| ---------------- | ------------------------ | ------------------------- | ---------------------------- |
| `workspace`      | `pages/Workspace/`       | `api/workspace.ts`        | Workspace 列表 / Dashboard   |
| `devinstance`    | `pages/Dev/`             | `api/dev-instance.ts`     | 开发机（包装 Spaces）        |
| `training`       | `pages/Training/`        | `api/training.ts`         | 训练任务                     |
| `inference`      | `pages/Inference/`       | —（Mock 为主）            | 推理服务                     |
| `experiment`     | `pages/Experiment/`      | —                         | MLflow 实验                  |
| `tasks`          | `pages/Tasks/`           | —                         | 跨类型任务总览               |
| `asset`          | `pages/Models/` + `Datasets/` + `Images/` | —       | 资产三件套（可拆可合）       |
| `admin`          | `pages/Admin/*`          | `api/cluster.ts` / `api/quota.ts` | 10 管理员页            |
| `auth`           | `pages/Login.tsx`        | `api/user.ts`             | 登录 / 当前用户              |
| `observability`  | —                        | `api/logs.ts` + `monitoring.ts` | 监控 + 日志（跨 feature）  |

`observability` 比较特殊：它为其他 feature 提供监控 panel。Wave 3 决定
它是一个 feature 还是提升到 `shared/ui`——取决于实际被引用次数。

## 每个 feature 的目录结构

```
features/<name>/
  index.ts          ← 公开出口（给 router 和其他 feature）
  pages/            ← 只放路由级 page 组件，负责布局 + 装配 components
  components/       ← feature 内部私有组件（DevInstanceCard / TrainingForm ...）
  api/              ← feature 独占的 API client + types
  hooks/            ← feature 内复用的 hooks（可选）
  types.ts          ← feature 内部类型别名（可选；小时内联到 api/）
  store.ts          ← feature 内 Zustand slice（可选；小时用 react state）
  routes.tsx        ← 本 feature 贡献的 RouteObject[]（Wave 3 开启集中路由后）
```

`index.ts` 典型长这样：

```ts
// 给 router 用的 pages
export { DevList } from './pages/List';
export { DevDetail } from './pages/Detail';

// 给其他 feature 偶尔用的 types / utils（尽量少）
export type { DevInstance } from './api/types';
```

## 硬性约束

1. **Feature 之间禁止互相 import。** `features/training` 不能 import
   `features/devinstance/...`。需要跨域共享 → 走 `shared/` 或事件总线。
2. **pages 只做路由 + 装配。** 业务逻辑、数据装载、状态编排都在
   components/hooks 里。这样"高级搜索加一个下拉"就 100% 在
   `features/<name>/components/` 内完成，不会再跨 5 个文件。
3. **api 文件夹只放 client + types。** 禁止 import 任何 React 组件或
   Zustand store——API 模块要在 jsdom 之外也能单测。
4. **只通过 `index.ts` 对外暴露。** 其他 feature 和路由永远只 import
   `@/features/<name>`（而不是 `@/features/<name>/components/...`），
   这样 feature 内部重构不污染外部。
5. **新 feature 先写 README。** `features/<name>/README.md` 一段话说明
   domain 边界、上游依赖、下游消费者——防止范围蔓延。

## 跨 feature 协作方式

- 共享 UI → 提升到 `shared/ui/`（例如 `StatusBadge`、`MainLayout`）。
- 共享 HTTP client → `shared/api/`。
- 共享 hooks → `shared/hooks/`（例如 `useDebouncedValue`）。
- 共享事件 → Wave 3 评估是否引入轻量事件总线（目前用 Zustand 全局 store 就够）。

## 什么时候可以打破规则

只有一种情况：**主责确认后在设计文档里写清楚"为什么"**。
否则按本规范办。
