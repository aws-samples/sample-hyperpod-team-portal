import { useMemo } from 'react';
import { Col, Row } from 'antd';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { generateTimeSeries } from '@/mock/metrics';
import { useAppStore } from '@/store';
import {
  baseLineOption,
  lineSeriesDefaults,
  SEMANTIC_COLORS,
  withAlpha,
} from './chartTheme';

interface Props {
  totalSteps: number;
}

type MetricDef = {
  key: string;
  title: string;
  unit: string;
  base: number;
  variance: number;
  seed: number;
  color: string;
  /** Optional trend modifier to make the curve go up or down over time. */
  trend?: (i: number, total: number, base: number) => number;
};

const METRICS: MetricDef[] = [
  {
    key: 'loss',
    title: 'Training Loss',
    unit: '',
    base: 2.8,
    variance: 0.15,
    seed: 101,
    color: SEMANTIC_COLORS.ttft, // loss uses "warning red" so anomalies pop
    // Exponential decay from 2.8 down to ~0.6
    trend: (i, total, base) => base * Math.exp(-2.5 * (i / total)) + 0.4,
  },
  {
    key: 'grad_norm',
    title: 'Gradient Norm',
    unit: '',
    base: 3.2,
    variance: 0.6,
    seed: 202,
    color: SEMANTIC_COLORS.itl,
  },
  {
    key: 'lr',
    title: 'Learning Rate',
    unit: '',
    base: 2e-5,
    variance: 0,
    seed: 303,
    color: SEMANTIC_COLORS.disk,
    // Warmup then linear decay
    trend: (i, total, base) => {
      const warmup = Math.min(1, (i / total) * 10);
      const decay = Math.max(0, 1 - Math.max(0, i / total - 0.1) / 0.9);
      return base * warmup * decay;
    },
  },
  {
    key: 'tokens_per_sec',
    title: 'Tokens / sec',
    unit: 'tok/s',
    base: 24_000,
    variance: 2_000,
    seed: 404,
    color: SEMANTIC_COLORS.throughput,
  },
];

export default function TrainingMetricsGrid({ totalSteps }: Props) {
  const themeMode = useAppStore((s) => s.themeMode);

  const options = useMemo<EChartsOption[]>(() => {
    const points = 80;
    return METRICS.map((m) => {
      const raw = generateTimeSeries(
        points,
        m.base,
        m.variance,
        undefined,
        60_000,
        m.seed,
      );
      const data = raw.map(([ts, v], i) => {
        const adjusted = m.trend ? m.trend(i, points, m.base) : m.base;
        const noise = (v - m.base) * 0.4;
        const final = adjusted + noise;
        return [ts, Number(final.toFixed(m.key === 'lr' ? 8 : 4))] as [
          number,
          number,
        ];
      });

      const baseOpt = baseLineOption(m.unit, [m.title], themeMode);
      const seriesCfg = lineSeriesDefaults(m.color);
      return {
        ...baseOpt,
        legend: undefined,
        // Training charts often have values spanning orders of magnitude (LR),
        // so unlock the scale clamp and leave the formatter to stringify.
        yAxis: {
          ...baseOpt.yAxis,
          scale: true,
          axisLabel: {
            fontSize: 10,
            color:
              themeMode === 'dark'
                ? 'rgba(255,255,255,0.65)'
                : 'rgba(0,0,0,0.65)',
            formatter: (v: number) =>
              m.key === 'lr'
                ? v.toExponential(1)
                : m.key === 'tokens_per_sec'
                ? `${(v / 1000).toFixed(1)}k`
                : v.toFixed(m.key === 'loss' ? 2 : 1),
          },
        },
        series: [
          {
            ...seriesCfg,
            name: m.title,
            data,
          },
        ],
      } satisfies EChartsOption;
    });
  }, [themeMode]);

  const cardBg = themeMode === 'dark' ? 'transparent' : '#fff';
  const cardBorder =
    themeMode === 'dark' ? withAlpha('#ffffff', 0.08) : '#f0f0f0';
  const titleColor =
    themeMode === 'dark' ? 'rgba(255,255,255,0.85)' : '#1f1f1f';
  const mutedColor =
    themeMode === 'dark' ? 'rgba(255,255,255,0.45)' : '#999';

  return (
    <Row gutter={[12, 12]}>
      {METRICS.map((m, i) => (
        <Col xs={24} md={12} key={m.key}>
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
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span>{m.title}</span>
              <span style={{ color: mutedColor, fontWeight: 400, fontSize: 11 }}>
                step 0 → {totalSteps}
              </span>
            </div>
            <ReactECharts
              option={options[i]}
              style={{ height: 220 }}
              notMerge
              lazyUpdate
            />
          </div>
        </Col>
      ))}
    </Row>
  );
}
