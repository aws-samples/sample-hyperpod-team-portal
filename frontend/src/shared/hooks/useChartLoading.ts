import { useEffect, useRef } from 'react';
import type ReactECharts from 'echarts-for-react';
import { loadingConfig } from '@/shared/ui/metrics/chartTheme';
import type { ThemeMode } from '@/store';

/**
 * Show the ECharts loading overlay for `durationMs` whenever any entry in the
 * `deps` array changes. Mimics the "querying metrics backend" feel of Grafana
 * / Datadog when switching granularity or time window — even though our data
 * is generated locally.
 *
 * Usage:
 *   const ref = useRef<ReactECharts>(null);
 *   useChartLoading(ref, themeMode, [granularity, timeRangeMin], 500);
 *
 * Rules:
 *   - The overlay is only shown when deps *change*, not on first mount with
 *     the initial values, unless `showOnMount` is true.
 *   - Hide is idempotent; safe to call even if we never showed anything.
 */
export function useChartLoading(
  chartRef: React.RefObject<ReactECharts>,
  mode: ThemeMode,
  deps: ReadonlyArray<unknown>,
  durationMs = 500,
  showOnMount = true,
) {
  const mounted = useRef(false);

  useEffect(() => {
    const inst = chartRef.current?.getEchartsInstance();
    if (!inst) return;
    if (!mounted.current && !showOnMount) {
      mounted.current = true;
      return;
    }
    mounted.current = true;
    inst.showLoading('default', loadingConfig(mode));
    const t = window.setTimeout(() => {
      // Instance may have been disposed by the time the timer fires.
      if (chartRef.current?.getEchartsInstance() === inst) {
        inst.hideLoading();
      }
    }, durationMs);
    return () => {
      window.clearTimeout(t);
      if (chartRef.current?.getEchartsInstance() === inst) {
        inst.hideLoading();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
