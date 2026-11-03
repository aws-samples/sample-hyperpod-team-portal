import { useMemo, useRef } from 'react';
import { Col, Row } from 'antd';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { generateTimeSeries } from '@/mock/metrics';
import { useAppStore } from '@/store';
import {
  baseLineOption,
  colorFor,
  lineSeriesDefaults,
  withAlpha,
  SEMANTIC_COLORS,
} from './chartTheme';
import { useChartLoading } from '@/shared/hooks/useChartLoading';

export type Granularity = 'job' | 'pod' | 'gpu';

interface Props {
  granularity: Granularity;
  selectedPods: string[];
  selectedGpuKeys: string[];
  timeRangeMinutes: number;
}

type MetricDef = {
  key: string;
  title: string;
  unit: string;
  base: number;
  variance: number;
  /** Optional soft upper bound (e.g. percentage charts clamp to 100). */
  max?: number;
  /** Semantic palette key — drives both line color and area gradient. */
  semantic: keyof typeof SEMANTIC_COLORS;
  /** Optional SLO/alert line rendered as a dashed marker. */
  sloLine?: { value: number; label: string; color?: string };
};

const METRICS: MetricDef[] = [
  {
    key: 'cpu',
    title: 'CPU 利用率',
    unit: '%',
    base: 45,
    variance: 15,
    max: 100,
    semantic: 'cpu',
  },
  {
    key: 'mem',
    title: '内存利用率',
    unit: '%',
    base: 62,
    variance: 10,
    max: 100,
    semantic: 'memory',
  },
  {
    key: 'gpu_util',
    title: 'GPU 算力利用率',
    unit: '%',
    base: 78,
    variance: 12,
    max: 100,
    semantic: 'gpu',
  },
  {
    key: 'gpu_mem',
    title: 'GPU 显存利用率',
    unit: '%',
    base: 68,
    variance: 8,
    max: 100,
    semantic: 'memory',
    sloLine: { value: 90, label: 'OOM Risk 90%' },
  },
  {
    key: 'gpu_sm',
    title: 'GPU SM 利用率',
    unit: '%',
    base: 72,
    variance: 15,
    max: 100,
    semantic: 'sm',
  },
  {
    key: 'network',
    title: '网络收发速率',
    unit: 'MB/s',
    base: 120,
    variance: 50,
    semantic: 'network',
  },
];

const seedFor = (s: string): number => {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h & 0xffff;
};

const resolveSeriesNames = (
  granularity: Granularity,
  selectedPods: string[],
  selectedGpuKeys: string[],
): string[] => {
  if (granularity === 'job') return ['job-avg'];
  if (granularity === 'pod') {
    return selectedPods.length > 0 ? selectedPods : ['master-0'];
  }
  return selectedGpuKeys.length > 0 ? selectedGpuKeys : ['master-0/gpu-0'];
};

/** Shade a semantic color slightly to create distinguishable per-series colors. */
const shadeSeries = (baseHex: string, idx: number): string => {
  // Rotate hue a small amount per series using HSL — keeps the palette "family"
  // but makes lines readable when multiple pods / GPUs are plotted together.
  const h = baseHex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  const factor = 1 - idx * 0.12;
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  return `rgb(${clamp(r * factor + 30 * (1 - factor))}, ${clamp(
    g * factor + 30 * (1 - factor),
  )}, ${clamp(b * factor + 60 * (1 - factor))})`;
};

export default function ResourceMetricsGrid({
  granularity,
  selectedPods,
  selectedGpuKeys,
  timeRangeMinutes,
}: Props) {
  const themeMode = useAppStore((s) => s.themeMode);

  const seriesNames = useMemo(
    () => resolveSeriesNames(granularity, selectedPods, selectedGpuKeys),
    [granularity, selectedPods, selectedGpuKeys],
  );

  const options = useMemo<EChartsOption[]>(() => {
    const points = Math.max(30, timeRangeMinutes);
    const intervalMs = Math.max(1, Math.floor((timeRangeMinutes * 60_000) / points));
    return METRICS.map((m) => {
      const baseColor = colorFor(m.semantic);
      const baseOpt = baseLineOption(m.unit, seriesNames, themeMode);
      const isNetwork = m.key === 'network';

      // Network chart renders RX/TX as two conceptual lines per selected host —
      // we use the semantic "network" amber for RX and a cooler pair color for TX.
      const series = isNetwork
        ? seriesNames.flatMap((name, idx) => {
            const rxSeed = seedFor(`${m.key}:rx:${name}:${granularity}`);
            const txSeed = seedFor(`${m.key}:tx:${name}:${granularity}`);
            const rxColor = shadeSeries(SEMANTIC_COLORS.network, idx);
            const txColor = shadeSeries(SEMANTIC_COLORS.gpu, idx);
            return [
              {
                ...lineSeriesDefaults(rxColor),
                name: `${name} RX`,
                data: generateTimeSeries(
                  points,
                  m.base,
                  m.variance,
                  undefined,
                  intervalMs,
                  rxSeed,
                ),
              },
              {
                ...lineSeriesDefaults(txColor),
                name: `${name} TX`,
                lineStyle: { width: 2, color: txColor, type: 'dashed' as const },
                data: generateTimeSeries(
                  points,
                  m.base * 0.6,
                  m.variance * 0.7,
                  undefined,
                  intervalMs,
                  txSeed,
                ),
              },
            ];
          })
        : seriesNames.map((name, idx) => {
            const seriesColor = shadeSeries(baseColor, idx);
            const cfg = lineSeriesDefaults(seriesColor);
            return {
              ...cfg,
              name,
              data: generateTimeSeries(
                points,
                m.base,
                m.variance,
                undefined,
                intervalMs,
                seedFor(`${m.key}:${name}:${granularity}`),
              ),
              // Attach SLO line to the first series only so it isn't drawn N times.
              ...(idx === 0 && m.sloLine
                ? {
                    markLine: {
                      silent: true,
                      symbol: 'none' as const,
                      lineStyle: {
                        color: m.sloLine.color ?? SEMANTIC_COLORS.errors,
                        type: 'dashed' as const,
                        width: 1,
                      },
                      label: {
                        formatter: m.sloLine.label,
                        color: m.sloLine.color ?? SEMANTIC_COLORS.errors,
                        fontSize: 10,
                        position: 'insideEndTop' as const,
                      },
                      data: [{ yAxis: m.sloLine.value }],
                    },
                  }
                : {}),
            };
          });

      const legendData = isNetwork
        ? seriesNames.flatMap((n) => [`${n} RX`, `${n} TX`])
        : seriesNames;

      return {
        ...baseOpt,
        legend: { ...baseOpt.legend, data: legendData },
        yAxis: { ...baseOpt.yAxis, ...(m.max ? { max: m.max, min: 0 } : {}) },
        series,
      } satisfies EChartsOption;
    });
  }, [seriesNames, granularity, timeRangeMinutes, themeMode]);

  const cardBg = themeMode === 'dark' ? 'transparent' : '#fff';
  const cardBorder =
    themeMode === 'dark' ? withAlpha('#ffffff', 0.08) : '#f0f0f0';
  const titleColor =
    themeMode === 'dark' ? 'rgba(255,255,255,0.85)' : '#1f1f1f';

  return (
    <Row gutter={[12, 12]}>
      {METRICS.map((m, i) => (
        <Col xs={24} md={12} key={m.key}>
          <ResourceChartCard
            title={m.title}
            option={options[i]}
            themeMode={themeMode}
            reloadKey={`${granularity}:${timeRangeMinutes}:${seriesNames.join(',')}`}
            cardBg={cardBg}
            cardBorder={cardBorder}
            titleColor={titleColor}
          />
        </Col>
      ))}
    </Row>
  );
}

/**
 * Per-chart wrapper — owns the ECharts ref so `useChartLoading` can trigger
 * the overlay on dependency changes without every metric having to manage it.
 */
function ResourceChartCard({
  title,
  option,
  themeMode,
  reloadKey,
  cardBg,
  cardBorder,
  titleColor,
}: {
  title: string;
  option: EChartsOption;
  themeMode: 'light' | 'dark';
  reloadKey: string;
  cardBg: string;
  cardBorder: string;
  titleColor: string;
}) {
  const chartRef = useRef<ReactECharts>(null);
  useChartLoading(chartRef, themeMode, [reloadKey], 500);
  return (
    <div
      style={{
        background: cardBg,
        borderRadius: 8,
        padding: 12,
        border: `1px solid ${cardBorder}`,
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 13,
          marginBottom: 4,
          color: titleColor,
        }}
      >
        {title}
      </div>
      <ReactECharts
        ref={chartRef}
        option={option}
        style={{ height: 220 }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}
