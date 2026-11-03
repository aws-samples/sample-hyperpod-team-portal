import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { Empty, Spin } from 'antd';
import { useTranslation } from 'react-i18next';
import { rangeQuery, type PromRangeResult, type QueryTemplate } from '@/api/monitoring';
import { useAppStore } from '@/store';
import { baseLineOption, colorFor, lineSeriesDefaults } from './chartTheme';

interface Props {
  template: QueryTemplate;
  /** Minutes of history to load (and refresh window). */
  rangeMinutes: number;
  /** Auto-refresh interval in seconds. 0 disables. */
  refreshSec?: number;
  /** Chart pixel height. */
  height?: number;
}

/**
 * Render one PromQL range-query as a multi-series line chart.
 *
 * Each distinct Prometheus series (combination of metric labels) becomes one
 * ECharts line. Label preference: pod → gpu → Hostname → series index.
 * Auto-refresh via setInterval; skipped when tab is hidden.
 */
export default function PromRangeChart({
  template,
  rangeMinutes,
  refreshSec = 20,
  height = 240,
}: Props) {
  const { t } = useTranslation('common');
  const themeMode = useAppStore((s) => s.themeMode);
  const [results, setResults] = useState<PromRangeResult[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const ranRef = useRef(0);
  // 容器可见性 · tab 切走 (display:none) 或滚出视口时为 false → 轮询照常 tick 但不发请求
  const rootRef = useRef<HTMLDivElement>(null);
  const visibleRef = useRef(true);
  const refetchRef = useRef<(() => void) | null>(null);

  // 不可见暂停请求, 重新可见立即补刷一次 (避免显示陈旧数据)
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver(
      ([e]) => {
        const wasVisible = visibleRef.current;
        visibleRef.current = e.isIntersecting;
        if (e.isIntersecting && !wasVisible) refetchRef.current?.();
      },
      { threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (document.hidden || !visibleRef.current) return;
      try {
        const now = Math.floor(Date.now() / 1000);
        const start = now - rangeMinutes * 60;
        const step = Math.max(15, Math.floor((rangeMinutes * 60) / 180));
        const resp = await rangeQuery(template.promql, start, now, step);
        if (cancelled) return;
        if (resp.status !== 'success' || !resp.data) {
          setErr(resp.error ?? 'unknown prometheus error');
          setResults([]);
        } else {
          setErr(null);
          setResults(resp.data.result as PromRangeResult[]);
        }
      } catch (e) {
        if (!cancelled) {
          setErr((e as Error).message);
          setResults([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    refetchRef.current = () => void run();
    ranRef.current += 1;
    if (ranRef.current === 1) setLoading(true);
    void run();
    if (refreshSec > 0) {
      const timer = setInterval(run, refreshSec * 1000);
      return () => {
        cancelled = true;
        clearInterval(timer);
      };
    }
    return () => {
      cancelled = true;
    };
  }, [template.promql, rangeMinutes, refreshSec]);

  const option: EChartsOption = useMemo(() => {
    const seriesMeta = (results ?? []).map((r, idx) => ({
      // 缺对应 label 则退化成 "series N" (Kueue 队列图靠 resource/status 分线)
      name:
        r.metric.pod ||
        r.metric.pod_name ||
        r.metric.gpu ||
        r.metric.Hostname ||
        r.metric.endpoint ||
        r.metric.status_code ||
        r.metric.resource ||
        r.metric.status ||
        r.metric.flavor ||
        `series ${idx + 1}`,
      values: r.values.map(([ts, v]) => [ts * 1000, Number(v)] as [number, number]),
    }));
    const names = seriesMeta.map((s) => s.name);
    const base = baseLineOption(template.unit, names, themeMode);
    if (seriesMeta.length === 0) return base;

    const series = seriesMeta.map((s, idx) => ({
      ...lineSeriesDefaults(colorFor('cpu', idx)),
      name: s.name,
      data: s.values,
    }));

    return {
      ...base,
      series,
    };
  }, [results, themeMode, template.unit]);

  // 单一 ref 容器: IntersectionObserver 需跨 loading/err/data 各态都挂得到同一元素
  const renderBody = () => {
    if (loading)
      return (
        <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Spin />
        </div>
      );
    if (err)
      return (
        <Empty
          description={t('metricsChart.loadFailed', { error: err.slice(0, 80) })}
          style={{ height, margin: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      );
    if (!results || results.length === 0)
      return (
        <Empty
          description={t('metricsChart.noData')}
          style={{ height, margin: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      );
    return <ReactECharts option={option} style={{ height, width: '100%' }} notMerge lazyUpdate />;
  };

  return (
    <div ref={rootRef} style={{ minHeight: height }}>
      {renderBody()}
    </div>
  );
}
