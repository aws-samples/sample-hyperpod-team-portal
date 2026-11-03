import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Segmented, Select, Space, Spin, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { useAppStore } from '@/store';
import { baseLineOption, lineSeriesDefaults, colorFor } from '@/shared/ui/metrics/chartTheme';
import {
  getFsxMetrics,
  listFsxFilesystems,
  fsxLabel,
  type FsxMetricSeries,
  type FsxMetricRange,
  type FsxOption,
} from '@/features/monitoring/api';
import { ApiError } from '@/shared/api';
import i18n from '@/shared/i18n';

const { Text } = Typography;

// ============================================================
// FSx CloudWatch 监控 (所有登录用户可看, 与工作空间无关)。
// 4 个核心指标趋势图, 样式复用开发机监控的 chartTheme。
// ============================================================

const BYTES_PER_GIB = 1024 ** 3;

// 统一绿色 (同开发机监控 colorFor('cpu'))。
const LINE_COLOR = colorFor('cpu');

// 一张图 = 一个 CloudWatch metric。每个 metric 单独一张图 (读/写不合并)。
// title = AWS console 上的显示名 (与 console 完全一致); metric = 后端 series key
// (CloudWatch MetricName 原文); desc = console 原文解释 (英文, 放标题小问号)。
interface ChartDef {
  metric: string; // CloudWatch MetricName 原文 (= 后端 series key)
  title: string; // AWS console 显示名
  unit: string;
  desc?: string; // console 原文解释 (英文), 无则不显小问号
  transform?: (v: number) => number; // 原始值 → 展示值 (仅换算, 不做 metric math)
}

// 标题 + 解释均取自 AWS FSx console (Storage / Performance / Metadata tab), 英文原文。
// metric = 后端返回的 series key (CloudWatch MetricName)。
const CHART_DEFS: ChartDef[] = [
  // --- Storage tab ---
  {
    metric: 'FreeDataStorageCapacity',
    title: 'Available storage capacity',
    unit: 'GiB',
    desc: 'The amount of available storage capacity (bytes) for your SSD storage tier.',
    transform: (v) => v / BYTES_PER_GIB,
  },
  {
    metric: 'StorageCapacityUtilization',
    title: 'Total storage capacity utilization',
    unit: '%',
    desc:
      'Storage utilization as a percentage of the total usable capacity of your file system '
      + '(percent) excluding space reserved for cached writes on clients.',
  },
  // --- Performance tab (Object storage performance) ---
  {
    metric: 'NetworkThroughputUtilization',
    title: 'Network throughput',
    unit: '%',
    desc:
      "The network throughput for clients accessing your file system's object storage server "
      + '(OSS), as a percentage of the provisioned limit determined by throughput capacity.',
  },
  {
    metric: 'FileServerDiskThroughputUtilization',
    title: 'Disk throughput',
    unit: '%',
    desc:
      'The disk throughput between your object storage server (OSS) and its storage volumes '
      + "(OST's), as a percentage of the provisioned limit determined by throughput capacity.",
  },
  {
    metric: 'DiskIopsUtilization',
    title: 'Disk IOPS',
    unit: '%',
    desc:
      "The utilization of your storage volumes (OST's) disk's provisioned IOPS, as a "
      + 'percentage of its limit determined by storage capacity.',
  },
  // --- Metadata performance tab ---
  {
    metric: 'CPUUtilization',
    title: 'CPU - utilization',
    unit: '%',
    desc: "The percentage utilization of your metadata server's CPU resources.",
  },
];

// label 存 key, 渲染时再 t()。
const RANGE_OPTION_DEFS = [
  { labelKey: 'pages.fsx.range.h1', value: '1h' },
  { labelKey: 'pages.fsx.range.h6', value: '6h' },
  { labelKey: 'pages.fsx.range.h24', value: '24h' },
] as const satisfies readonly { labelKey: string; value: FsxMetricRange }[];

function friendlyError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const raw = (e.message || '').trim();
    if (e.status && raw) return `${raw} (HTTP ${e.status})`;
    if (raw) return raw;
    if (e.status) return i18n.t('pages.fsx.requestFailed', { ns: 'monitoring', status: e.status });
  }
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

/** 单 metric 趋势图 option — 复用开发机监控的 chartTheme。 */
function trendOption(c: ChartDef, series: FsxMetricSeries, mode: 'light' | 'dark'): EChartsOption {
  const raw = series[c.metric] ?? [];
  const data: [number, number][] = raw.map(([ts, v]) => [
    Date.parse(ts),
    c.transform ? c.transform(v) : v,
  ]);
  const base = baseLineOption(c.unit, [c.title], mode);
  return {
    ...base,
    legend: { show: false },
    grid: { left: 60, right: 20, top: 16, bottom: 24, containLabel: false },
    series: [{ ...lineSeriesDefaults(LINE_COLOR), name: c.title, data }],
  };
}

export default function MonitoringFsx() {
  const { t } = useTranslation(['monitoring', 'common']);
  const [metrics, setMetrics] = useState<FsxMetricSeries>({});
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState<FsxMetricRange>('1h');
  // 多 FSx: 顶部下拉选盘, 选哪个看哪个的监控。
  const [fsList, setFsList] = useState<FsxOption[]>([]);
  const [fsId, setFsId] = useState<string>('');
  const [fsLoading, setFsLoading] = useState(true); // FSx 列表加载中 (describe 各盘)
  const themeMode = useAppStore((s) => s.themeMode);

  // 快速切时间范围时请求可能乱序返回, 用自增 id 只认最后一次。
  const metricsReqId = useRef(0);

  // 进页面先拉 FSx 列表, 默认选第一个。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setFsLoading(true);
      try {
        const list = await listFsxFilesystems();
        if (cancelled) return;
        setFsList(list);
        if (list.length > 0) setFsId(list[0].filesystemId);
        else setLoading(false); // 无盘可选, 不会触发 loadMetrics
      } catch {
        if (!cancelled) {
          setMetricsError(t('pages.fsx.loadListFailed'));
          setLoading(false);
        }
      } finally {
        if (!cancelled) setFsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const loadMetrics = useCallback(async (fs: string, rng: FsxMetricRange) => {
    if (!fs) return;
    const reqId = ++metricsReqId.current;
    setMetricsError(null);
    setLoading(true);
    try {
      const series = await getFsxMetrics(fs, rng);
      if (reqId !== metricsReqId.current) return; // 已有更新的请求, 丢弃本次
      setMetrics(series);
    } catch (e) {
      if (reqId !== metricsReqId.current) return;
      setMetricsError(friendlyError(e, t('pages.fsx.loadMetricsFailed')));
      setMetrics({});
    } finally {
      // 仅最新请求负责关 loading (旧请求提前 return 不会走到这)
      if (reqId === metricsReqId.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (fsId) void loadMetrics(fsId, range);
  }, [fsId, range, loadMetrics]);

  return (
    <PageContainer header={{ title: t('pages.fsx.title') }}>
      <ProCard
        bordered
        title={t('pages.fsx.title')}
        subTitle={
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('pages.fsx.dataSource')}
          </Text>
        }
        extra={
          <Space size={8}>
            <Select<string>
              size="small"
              style={{ minWidth: 180 }}
              value={fsId || undefined}
              loading={fsLoading}
              disabled={fsLoading}
              placeholder={fsLoading ? t('pages.fsx.loadingFsx') : t('pages.fsx.selectFsx')}
              onChange={(v) => setFsId(v)}
              options={fsList.map((f) => ({
                value: f.filesystemId,
                label: fsxLabel(f),
              }))}
            />
            <Segmented<FsxMetricRange>
              size="small"
              value={range}
              onChange={(v) => setRange(v)}
              options={RANGE_OPTION_DEFS.map((o) => ({ label: t(o.labelKey), value: o.value }))}
            />
          </Space>
        }
      >
        {metricsError ? (
          // 监控拉取失败: 图区居中一行淡色提示 + 重试。
          <div
            style={{
              height: 220,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 10,
              color: 'rgba(0,0,0,0.45)',
              fontSize: 13,
            }}
          >
            <span>{metricsError}</span>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadMetrics(fsId, range)}>
              {t('common:actions.retry')}
            </Button>
          </div>
        ) : (
          <ProCard gutter={[16, 16]} ghost wrap>
            {CHART_DEFS.map((c) => (
              <ProCard
                key={c.metric}
                colSpan={{ xs: 24, md: 12 }}
                bordered
                title={
                  <Space size={4}>
                    <Text style={{ fontSize: 13 }}>{c.title}</Text>
                    {c.desc ? (
                      <Tooltip title={c.desc}>
                        <QuestionCircleOutlined
                          style={{ color: '#999', fontSize: 12, cursor: 'help' }}
                        />
                      </Tooltip>
                    ) : null}
                  </Space>
                }
                headerBordered
                bodyStyle={{ padding: 8 }}
              >
                {loading ? (
                  // 与开发机监控图一致: loading 时不渲图, 居中放 AntD Spin (点点转圈)
                  <div
                    style={{
                      height: 220,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Spin />
                  </div>
                ) : (
                  <ReactECharts
                    option={trendOption(c, metrics, themeMode)}
                    style={{ height: 220, width: '100%' }}
                    notMerge
                    lazyUpdate
                  />
                )}
              </ProCard>
            ))}
          </ProCard>
        )}
      </ProCard>
    </PageContainer>
  );
}
