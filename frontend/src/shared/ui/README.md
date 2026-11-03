# shared/ui

Cross-feature reusable UI primitives. After Wave 3 migration this folder
will host the true "framework" pieces that every feature depends on.

## Migration targets (Wave 3)

Current location → target:

| 旧路径                                     | 新路径                           | 备注                                 |
| ------------------------------------------ | -------------------------------- | ------------------------------------ |
| `src/layouts/MainLayout.tsx`               | `src/shared/ui/MainLayout.tsx`   | 顶层 shell、侧边栏、头               |
| `src/components/common/StatusBadge.tsx`    | `src/shared/ui/StatusBadge.tsx`  | 通用状态色块                         |
| `src/components/common/QuotaPreviewBar.tsx`| `src/shared/ui/QuotaPreviewBar` | 跨创建页通用                         |
| `src/components/common/ResourcePoolPicker` | `src/shared/ui/ResourcePoolPicker` | 跨创建页通用                       |
| `src/components/metrics/chartTheme.ts`     | `src/shared/ui/charts/theme.ts`  | ECharts 共享主题                     |

监控系列组件（`ResourceMetricsGrid` / `LLMMetricsGrid` / `LogViewer` /
`PromRangeChart` / `TrainingMetricsGrid` / `MonitoringTabPanel`）属于
**observability feature** 还是 **shared/ui** 尚未决定，Wave 3 启动前
由主责评估（若被 3 个以上 feature 引用则归 shared/ui，否则归 feature）。

## 原则

- `shared/ui` 里的组件 **不得** 依赖任何具体 feature（反向依赖禁止）。
- 只依赖 `antd` / `@ant-design/pro-components` / `echarts` / `react` 等
  第三方库，以及 `@/shared/hooks` · `@/shared/api` 自身。
- 任何 feature 独有的业务组件（例如 `DevInstanceCard`）留在
  `features/<name>/components/`，不要误入这里。
