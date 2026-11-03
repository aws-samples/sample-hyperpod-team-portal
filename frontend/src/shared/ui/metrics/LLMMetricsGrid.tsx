import { useMemo, useRef } from 'react';
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
import { useChartLoading } from '@/shared/hooks/useChartLoading';
import type { ThemeMode } from '@/store';

interface Props {
  replicas: string[];
  timeRangeMinutes: number;
}

/* ============================================================================
 * LLM metrics — six panels tuned for vLLM / TGI-style inference dashboards.
 *
 * Each panel uses its semantic color from the palette (latency = red family,
 * throughput = green, cache = purple, errors = deep red) and surfaces SLO
 * thresholds as dashed markLines so the screenshot tells a story at a glance.
 * ========================================================================== */

const shadeReplica = (baseHex: string, idx: number): string => {
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

/** Shared chart card for this grid, handles theme-aware background + loading. */
function LLMChartCard({
  title,
  hint,
  option,
  themeMode,
  reloadKey,
}: {
  title: string;
  hint: string;
  option: EChartsOption;
  themeMode: ThemeMode;
  reloadKey: string;
}) {
  const chartRef = useRef<ReactECharts>(null);
  useChartLoading(chartRef, themeMode, [reloadKey], 500);

  const cardBg = themeMode === 'dark' ? 'transparent' : '#fff';
  const cardBorder =
    themeMode === 'dark' ? withAlpha('#ffffff', 0.08) : '#f0f0f0';
  const titleColor =
    themeMode === 'dark' ? 'rgba(255,255,255,0.85)' : '#1f1f1f';
  const hintColor =
    themeMode === 'dark' ? 'rgba(255,255,255,0.45)' : '#999';

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
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 4,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13, color: titleColor }}>
          {title}
        </span>
        <span style={{ color: hintColor, fontSize: 11 }}>{hint}</span>
      </div>
      <ReactECharts
        ref={chartRef}
        option={option}
        style={{ height: 240 }}
        notMerge
        lazyUpdate
      />
    </div>
  );
}

export default function LLMMetricsGrid({ replicas, timeRangeMinutes }: Props) {
  const themeMode = useAppStore((s) => s.themeMode);
  const points = Math.max(40, timeRangeMinutes);
  const reloadKey = `${timeRangeMinutes}:${replicas.join(',')}`;

  // TTFT p50/p95/p99 — gradient from yellow→red to show percentile escalation.
  const ttftOption = useMemo<EChartsOption>(() => {
    const opt = baseLineOption('ms', ['p50', 'p95', 'p99'], themeMode);
    const p50Color = SEMANTIC_COLORS.itl;
    const p95Color = '#ff7a45';
    const p99Color = SEMANTIC_COLORS.ttft;
    return {
      ...opt,
      series: [
        {
          ...lineSeriesDefaults(p50Color),
          name: 'p50',
          data: generateTimeSeries(points, 187, 28, undefined, 60_000, 11),
        },
        {
          ...lineSeriesDefaults(p95Color),
          name: 'p95',
          data: generateTimeSeries(points, 330, 40, undefined, 60_000, 22),
        },
        {
          ...lineSeriesDefaults(p99Color),
          name: 'p99',
          data: generateTimeSeries(points, 420, 70, undefined, 60_000, 33),
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: {
              color: SEMANTIC_COLORS.errors,
              type: 'dashed',
              width: 1,
            },
            label: {
              formatter: 'SLO 500ms',
              color: SEMANTIC_COLORS.errors,
              fontSize: 10,
              position: 'insideEndTop',
            },
            data: [{ yAxis: 500 }],
          },
        },
      ],
    };
  }, [points, themeMode]);

  const itlOption = useMemo<EChartsOption>(() => {
    const opt = baseLineOption('ms', ['input-only', 'mixed'], themeMode);
    return {
      ...opt,
      series: [
        {
          ...lineSeriesDefaults(SEMANTIC_COLORS.itl),
          name: 'input-only',
          data: generateTimeSeries(points, 38, 6, undefined, 60_000, 44),
        },
        {
          ...lineSeriesDefaults('#fa541c'),
          name: 'mixed',
          data: generateTimeSeries(points, 52, 8, undefined, 60_000, 55),
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: {
              color: SEMANTIC_COLORS.errors,
              type: 'dashed',
              width: 1,
            },
            label: {
              formatter: 'SLO 80ms',
              color: SEMANTIC_COLORS.errors,
              fontSize: 10,
              position: 'insideEndTop',
            },
            data: [{ yAxis: 80 }],
          },
        },
      ],
    };
  }, [points, themeMode]);

  const throughputOption = useMemo<EChartsOption>(() => {
    const opt = baseLineOption('tok/s', ['prompt', 'decode'], themeMode);
    const yAxisBase = opt.yAxis as Record<string, unknown>;
    return {
      ...opt,
      yAxis: {
        ...yAxisBase,
        axisLabel: {
          ...((yAxisBase.axisLabel as Record<string, unknown>) ?? {}),
          formatter: (v: number) => `${(v / 1000).toFixed(1)}k`,
        },
      } as EChartsOption['yAxis'],
      series: [
        {
          ...lineSeriesDefaults('#1677ff'),
          name: 'prompt',
          data: generateTimeSeries(points, 1_200, 180, undefined, 60_000, 66),
        },
        {
          ...lineSeriesDefaults(SEMANTIC_COLORS.throughput),
          name: 'decode',
          data: generateTimeSeries(points, 2_340, 260, undefined, 60_000, 77),
        },
      ],
    };
  }, [points, themeMode]);

  const qpsOption = useMemo<EChartsOption>(() => {
    const opt = baseLineOption('req/s', replicas, themeMode);
    return {
      ...opt,
      series: replicas.map((r, idx) => ({
        ...lineSeriesDefaults(shadeReplica(SEMANTIC_COLORS.qps, idx)),
        name: r,
        data: generateTimeSeries(
          points,
          43 - idx * 4,
          6,
          undefined,
          60_000,
          88 + idx * 7,
        ),
      })),
    };
  }, [points, replicas, themeMode]);

  const kvCacheOption = useMemo<EChartsOption>(() => {
    const opt = baseLineOption('%', replicas, themeMode);
    return {
      ...opt,
      yAxis: { ...opt.yAxis, max: 100, min: 0 },
      series: replicas.map((r, idx) => ({
        ...lineSeriesDefaults(shadeReplica(SEMANTIC_COLORS.kvcache, idx)),
        name: r,
        data: generateTimeSeries(
          points,
          67 + idx * 5,
          9,
          undefined,
          60_000,
          99 + idx * 3,
        ),
        ...(idx === 0
          ? {
              markLine: {
                silent: true,
                symbol: 'none' as const,
                lineStyle: {
                  color: SEMANTIC_COLORS.errors,
                  type: 'dashed' as const,
                  width: 1,
                },
                label: {
                  formatter: 'Danger 90%',
                  color: SEMANTIC_COLORS.errors,
                  fontSize: 10,
                  position: 'insideEndTop' as const,
                },
                data: [{ yAxis: 90, name: 'danger' }],
              },
            }
          : {}),
      })),
    };
  }, [points, replicas, themeMode]);

  const errorOption = useMemo<EChartsOption>(() => {
    const opt = baseLineOption('%', ['5xx', '4xx'], themeMode);
    return {
      ...opt,
      yAxis: { ...opt.yAxis, max: 5, min: 0 },
      series: [
        {
          ...lineSeriesDefaults(SEMANTIC_COLORS.errors),
          name: '5xx',
          data: generateTimeSeries(points, 0.2, 0.3, undefined, 60_000, 121),
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: {
              color: SEMANTIC_COLORS.errors,
              type: 'dashed',
              width: 1,
            },
            label: {
              formatter: 'SLO 1%',
              color: SEMANTIC_COLORS.errors,
              fontSize: 10,
              position: 'insideEndTop',
            },
            data: [{ yAxis: 1 }],
          },
        },
        {
          ...lineSeriesDefaults('#faad14'),
          name: '4xx',
          data: generateTimeSeries(points, 0.8, 0.4, undefined, 60_000, 132),
        },
      ],
    };
  }, [points, themeMode]);

  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} md={12}>
        <LLMChartCard
          title="TTFT 分位线"
          hint="Time to First Token · SLO 500ms"
          option={ttftOption}
          themeMode={themeMode}
          reloadKey={`ttft:${reloadKey}`}
        />
      </Col>
      <Col xs={24} md={12}>
        <LLMChartCard
          title="ITL 延迟"
          hint="Inter-Token Latency · SLO 80ms"
          option={itlOption}
          themeMode={themeMode}
          reloadKey={`itl:${reloadKey}`}
        />
      </Col>
      <Col xs={24} md={12}>
        <LLMChartCard
          title="Token 吞吐"
          hint="prompt vs decode tokens/s"
          option={throughputOption}
          themeMode={themeMode}
          reloadKey={`thr:${reloadKey}`}
        />
      </Col>
      <Col xs={24} md={12}>
        <LLMChartCard
          title="QPS (按副本)"
          hint="Requests per second"
          option={qpsOption}
          themeMode={themeMode}
          reloadKey={`qps:${reloadKey}`}
        />
      </Col>
      <Col xs={24} md={12}>
        <LLMChartCard
          title="KV Cache 使用率"
          hint="红线 = 90% 告警阈值"
          option={kvCacheOption}
          themeMode={themeMode}
          reloadKey={`kv:${reloadKey}`}
        />
      </Col>
      <Col xs={24} md={12}>
        <LLMChartCard
          title="错误率"
          hint="5xx 服务错误 / 4xx 客户端错误"
          option={errorOption}
          themeMode={themeMode}
          reloadKey={`err:${reloadKey}`}
        />
      </Col>
    </Row>
  );
}
