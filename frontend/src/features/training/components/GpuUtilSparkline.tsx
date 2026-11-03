/**
 * 总览 Tab 顶部 GPU 利用率小图.
 * 直接调一次 rangeQuery 拉 15 分钟 avg, 不复用 MonitoringTabPanel
 * (避免引入 dim/range/refresh 选择器的视觉负担).
 */
import { useEffect, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { Empty, Spin } from 'antd';
import {
  listTrainingTemplates,
  rangeQuery,
  type PromRangeResult,
} from '@/api/monitoring';
import { useAppStore } from '@/store';
import { baseLineOption, colorFor, lineSeriesDefaults } from '@/shared/ui/metrics/chartTheme';

interface Props {
  trainingJobId: string;
  height?: number;
}

const RANGE_MIN = 15;
const TARGET_KEY = 'job_gpu_util_avg';

export default function GpuUtilSparkline({ trainingJobId, height = 100 }: Props) {
  const themeMode = useAppStore((s) => s.themeMode);
  const [points, setPoints] = useState<[number, number][] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const templates = await listTrainingTemplates(trainingJobId);
        const tpl = templates.find((t) => t.key === TARGET_KEY);
        if (!tpl) {
          if (!cancelled) setPoints([]);
          return;
        }
        const now = Math.floor(Date.now() / 1000);
        const start = now - RANGE_MIN * 60;
        const resp = await rangeQuery(tpl.promql, start, now, 30);
        if (cancelled) return;
        if (resp.status !== 'success' || !resp.data?.result?.length) {
          setPoints([]);
          return;
        }
        const first = (resp.data.result as PromRangeResult[])[0];
        const series = first?.values ?? [];
        setPoints(series.map(([ts, v]) => [ts * 1000, parseFloat(v)]));
      } catch {
        if (!cancelled) setPoints([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [trainingJobId]);

  if (loading) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="small" />
      </div>
    );
  }

  if (!points || points.length === 0) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无数据 (任务刚启动或 Prometheus 还没采到)"
        />
      </div>
    );
  }

  const option: EChartsOption = {
    ...baseLineOption('%', ['GPU 平均利用率'], themeMode),
    grid: { left: 40, right: 12, top: 10, bottom: 24 },
    legend: { show: false },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series: [
      {
        ...lineSeriesDefaults(colorFor('gpu', 0)),
        name: 'GPU 平均利用率',
        data: points,
      },
    ],
  };

  return <ReactECharts option={option} style={{ height }} notMerge lazyUpdate />;
}
