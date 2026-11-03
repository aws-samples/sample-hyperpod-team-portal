import type { EChartsSeriesPoint } from '@/types';

/**
 * Deterministic pseudo-random so the same inputs always produce the same
 * curve — avoids flicker when re-rendering.
 */
const seededRandom = (seed: number): (() => number) => {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
};

/**
 * Generate an ECharts-ready time series.
 *
 * @param points   Number of samples.
 * @param base     Baseline value.
 * @param variance Max +/- random variance around the baseline.
 * @param startTs  Unix ms of the first point. Defaults to (now - points * 60s).
 * @param intervalMs Spacing between points. Defaults to 60 seconds.
 * @param seed     RNG seed for deterministic output.
 */
export function generateTimeSeries(
  points: number,
  base: number,
  variance: number,
  startTs?: number,
  intervalMs = 60_000,
  seed = 42,
): EChartsSeriesPoint[] {
  const rand = seededRandom(seed);
  const start = startTs ?? Date.now() - points * intervalMs;
  const result: EChartsSeriesPoint[] = [];
  for (let i = 0; i < points; i += 1) {
    const ts = start + i * intervalMs;
    const value = base + (rand() * 2 - 1) * variance;
    result.push([ts, Number(value.toFixed(3))]);
  }
  return result;
}
