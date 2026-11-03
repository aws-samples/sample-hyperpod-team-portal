/**
 * Barrel for the shared metrics UI primitives. Consumed cross-feature by
 * training / inference / dev-instance / admin / experiment pages.
 *
 * Wave 3 (C3) migration: moved from `src/components/metrics/` because these
 * components are referenced by 4+ features (admin, inference, training,
 * dev-instance, experiment) — clearly shared infrastructure rather than
 * feature-owned.
 */
export {
  SEMANTIC_COLORS,
  CHART_PALETTE,
  colorFor,
  areaGradient,
  withAlpha,
  baseLineOption,
  lineSeriesDefaults,
  loadingConfig,
  type SemanticKey,
} from './chartTheme';

export { default as ResourceMetricsGrid } from './ResourceMetricsGrid';
export type { Granularity } from './ResourceMetricsGrid';
export { default as LLMMetricsGrid } from './LLMMetricsGrid';
export { default as LLMKpiRow } from './LLMKpiRow';
export { default as LogViewer } from './LogViewer';
export { default as PromRangeChart } from './PromRangeChart';
export { default as TrainingMetricsGrid } from './TrainingMetricsGrid';
export { default as MonitoringTabPanel } from './MonitoringTabPanel';
