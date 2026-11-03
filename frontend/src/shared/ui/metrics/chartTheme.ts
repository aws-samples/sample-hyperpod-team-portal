import type { EChartsOption } from 'echarts';
import * as echarts from 'echarts/core';
import type { ThemeMode } from '@/store';
import i18n, { currentLocale } from '@/shared/i18n';

/* ============================================================================
 * Chart Theme — Grafana / Datadog-grade styling for every ECharts instance.
 *
 * Design principles:
 *   1. Dual-mode first: every color token has a light + dark variant, selected
 *      at render time from the current `themeMode` in the app store.
 *   2. Semantic palette: series colors are picked by meaning (latency=red,
 *      throughput=green, memory=cyan) instead of insertion order.
 *   3. Minimal chrome: no axis line, dashed gridlines, tight tooltip with a
 *      colored dot per series — keeps the data dense and reads like a
 *      professional observability dashboard.
 * ========================================================================== */

/**
 * Semantic color map — every chart series should pick its color from this
 * lookup by business meaning. The indexed `CHART_PALETTE` below is exported
 * for the (rare) case where a chart just wants N distinct colors.
 */
export const SEMANTIC_COLORS = {
  gpu: '#0958d9',
  memory: '#13c2c2',
  cpu: '#52c41a',
  network: '#faad14',
  disk: '#722ed1',
  sm: '#eb2f96',
  ttft: '#f5222d',
  itl: '#fa8c16',
  throughput: '#52c41a',
  kvcache: '#722ed1',
  qps: '#0958d9',
  errors: '#cf1322',
} as const;

export type SemanticKey = keyof typeof SEMANTIC_COLORS;

/** Ordered palette for charts that don't map by semantic meaning. */
export const CHART_PALETTE: string[] = [
  SEMANTIC_COLORS.gpu,
  SEMANTIC_COLORS.memory,
  SEMANTIC_COLORS.cpu,
  SEMANTIC_COLORS.network,
  SEMANTIC_COLORS.disk,
  SEMANTIC_COLORS.sm,
  SEMANTIC_COLORS.itl,
  SEMANTIC_COLORS.errors,
];

/** Pick a color by semantic key with fall-through to the palette. */
export const colorFor = (key: SemanticKey | string, fallbackIndex = 0): string => {
  if (key in SEMANTIC_COLORS) {
    return SEMANTIC_COLORS[key as SemanticKey];
  }
  return CHART_PALETTE[fallbackIndex % CHART_PALETTE.length];
};

interface Palette {
  axisText: string;
  axisLine: string;
  splitLine: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  tooltipShadow: string;
  legendText: string;
  crossHair: string;
}

/** Two palettes that cover every non-series color in the chart surface. */
const LIGHT: Palette = {
  axisText: 'rgba(0, 0, 0, 0.65)',
  axisLine: '#d9d9d9',
  splitLine: '#f0f0f0',
  tooltipBg: 'rgba(255, 255, 255, 0.98)',
  tooltipBorder: '#e5e7eb',
  tooltipText: '#1f1f1f',
  tooltipShadow: '0 6px 24px -4px rgba(15, 23, 42, 0.18)',
  legendText: 'rgba(0, 0, 0, 0.75)',
  crossHair: 'rgba(9, 88, 217, 0.45)',
};

const DARK: Palette = {
  axisText: 'rgba(255, 255, 255, 0.65)',
  axisLine: '#2a3040',
  splitLine: '#1f2530',
  tooltipBg: 'rgba(20, 20, 30, 0.92)',
  tooltipBorder: 'rgba(255, 255, 255, 0.12)',
  tooltipText: 'rgba(255, 255, 255, 0.92)',
  tooltipShadow: '0 10px 28px -8px rgba(0, 0, 0, 0.65)',
  legendText: 'rgba(255, 255, 255, 0.78)',
  crossHair: 'rgba(105, 177, 255, 0.55)',
};

const paletteFor = (mode: ThemeMode): Palette => (mode === 'dark' ? DARK : LIGHT);

/**
 * Build a linear-gradient area fill for a smoothed line chart. Goes from the
 * series color at 0.2 opacity down to effectively transparent — gives the
 * "Grafana polished" visual weight without overpowering the line.
 */
export const areaGradient = (hex: string): echarts.graphic.LinearGradient =>
  new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: withAlpha(hex, 0.2) },
    { offset: 1, color: withAlpha(hex, 0.02) },
  ]);

/** Convert a #rrggbb hex into rgba() with the given alpha. */
export const withAlpha = (hex: string, alpha: number): string => {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

/**
 * Extended formatter helpers — charts pass in a unit symbol and we decide how
 * to stringify numbers. Keeps a consistent "187 ms" / "2,340 tok/s" style.
 */
const formatValue = (v: unknown, unit: string): string => {
  if (typeof v !== 'number' || !Number.isFinite(v)) return `${v} ${unit}`.trim();
  const abs = Math.abs(v);
  let str: string;
  if (abs >= 10_000) str = v.toFixed(0);
  else if (abs >= 100) str = v.toFixed(1);
  else if (abs >= 1) str = v.toFixed(2);
  else str = v.toFixed(3);
  // Strip trailing zeros like "1.00" → "1" for cleaner tooltip labels.
  str = str.replace(/\.?0+$/, '');
  return unit ? `${str} ${unit}` : str;
};

/**
 * Build the tooltip formatter. Emits a header line with the axis timestamp
 * and one row per series with a colored dot, series name, and formatted value.
 * Mirrors the Grafana tooltip layout that most ops engineers are used to.
 */
const buildTooltipFormatter = (unit: string, palette: Palette) =>
  (raw: unknown): string => {
    const params = Array.isArray(raw) ? raw : [raw];
    if (params.length === 0) return '';
    type Row = {
      axisValueLabel?: string;
      axisValue?: number | string;
      seriesName?: string;
      color?: string;
      value?: unknown;
    };
    const rows = params as Row[];
    const head =
      rows[0].axisValueLabel ??
      (typeof rows[0].axisValue === 'number'
        ? new Date(rows[0].axisValue).toLocaleTimeString(currentLocale())
        : String(rows[0].axisValue ?? ''));

    const body = rows
      .map((p) => {
        const color = p.color ?? '#999';
        const name = p.seriesName ?? '';
        const val = Array.isArray(p.value)
          ? (p.value as unknown[])[1]
          : p.value;
        return `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;line-height:20px;">
            <span style="display:inline-flex;align-items:center;gap:6px;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};box-shadow:0 0 0 2px ${withAlpha(
                color,
                0.18,
              )};"></span>
              <span style="color:${palette.tooltipText};opacity:0.85;">${name}</span>
            </span>
            <span style="color:${palette.tooltipText};font-weight:600;font-variant-numeric:tabular-nums;">${formatValue(
              val,
              unit,
            )}</span>
          </div>`;
      })
      .join('');

    return `
      <div style="min-width:180px;">
        <div style="color:${palette.tooltipText};opacity:0.6;font-size:11px;margin-bottom:6px;letter-spacing:0.2px;">${head}</div>
        ${body}
      </div>`;
  };

/**
 * Y 轴刻度只显数值 (单位放图标题, 不在每个刻度重复拼).
 * 大数用 k/M/G 缩写; 小数按量级给精度; 0 显 "0".
 * 仅 "%" 例外 — 百分号紧贴数值是通用习惯, 不占额外宽度.
 */
const axisFormatterFor = (unit: string) => (v: number) => {
  if (!Number.isFinite(v)) return String(v);
  const pct = unit === '%' ? '%' : '';
  const abs = Math.abs(v);
  if (abs === 0) return `0${pct}`;
  if (abs >= 1_000_000_000) return `${+(v / 1_000_000_000).toFixed(1)}G${pct}`;
  if (abs >= 1_000_000) return `${+(v / 1_000_000).toFixed(1)}M${pct}`;
  if (abs >= 1_000) return `${+(v / 1_000).toFixed(1)}k${pct}`;
  if (abs >= 1) return `${+v.toFixed(1)}${pct}`;
  return `${+v.toFixed(2)}${pct}`;
};

/**
 * Full baseline EChartsOption — apply `{...baseLineOption(unit, names, mode), series: [...]}`.
 * Every subsequent spread in a caller will override these defaults cleanly.
 */
export const baseLineOption = (
  unit: string,
  seriesNames: string[],
  mode: ThemeMode = 'light',
): EChartsOption => {
  const p = paletteFor(mode);
  return {
    backgroundColor: 'transparent',
    color: CHART_PALETTE,
    textStyle: {
      color: p.axisText,
      fontFamily:
        '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    },
    grid: { left: 50, right: 20, top: 40, bottom: 30, containLabel: false },
    legend: {
      type: 'scroll',
      top: 6,
      right: 12,
      data: seriesNames,
      textStyle: { fontSize: 11, color: p.legendText },
      itemWidth: 12,
      itemHeight: 8,
      itemGap: 12,
      icon: 'roundRect',
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.tooltipBg,
      borderColor: p.tooltipBorder,
      borderWidth: 1,
      padding: [10, 12, 10, 12],
      extraCssText: `box-shadow:${p.tooltipShadow};border-radius:8px;backdrop-filter:blur(8px);`,
      textStyle: { color: p.tooltipText, fontSize: 12 },
      axisPointer: {
        type: 'line',
        lineStyle: { type: 'dashed', color: p.crossHair, width: 1 },
        label: { show: false },
      },
      formatter: buildTooltipFormatter(unit, p),
    },
    xAxis: {
      type: 'time',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: p.axisText,
        hideOverlap: true,
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        fontSize: 10,
        color: p.axisText,
        formatter: axisFormatterFor(unit),
      },
      splitLine: {
        show: true,
        lineStyle: { type: 'dashed', color: p.splitLine, opacity: 0.8 },
      },
    },
    animation: true,
    animationDuration: 420,
    animationEasing: 'cubicOut',
  };
};

/**
 * Build the shared "smooth line" series defaults — apply via `{...lineSeriesDefaults(color), name, data}`.
 * Keeps line width, symbol, area gradient, and hover emphasis consistent
 * across all monitoring charts.
 */
export const lineSeriesDefaults = (color: string) => ({
  type: 'line' as const,
  smooth: 0.3,
  showSymbol: false,
  symbol: 'circle' as const,
  symbolSize: 6,
  sampling: 'lttb' as const,
  lineStyle: { width: 2, color },
  itemStyle: { color },
  areaStyle: { color: areaGradient(color) },
  emphasis: {
    focus: 'series' as const,
    lineStyle: { width: 3 },
    scale: true,
  },
});

/**
 * Loading overlay configuration — keep the style in sync with the theme so the
 * spinner blends into the chart surface instead of popping.
 */
export const loadingConfig = (mode: ThemeMode) => ({
  text: i18n.t('metricsChart.loading', { ns: 'common' }),
  color: SEMANTIC_COLORS.gpu,
  textColor: paletteFor(mode).axisText,
  maskColor:
    mode === 'dark' ? 'rgba(15, 20, 25, 0.55)' : 'rgba(255, 255, 255, 0.65)',
  zlevel: 0,
  fontSize: 12,
  showSpinner: true,
  spinnerRadius: 10,
  lineWidth: 2,
});
