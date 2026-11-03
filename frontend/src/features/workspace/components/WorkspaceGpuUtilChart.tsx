import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import {
  Button,
  Col,
  Empty,
  Modal,
  Row,
  Segmented,
  Space,
  Spin,
  Tooltip,
  Typography,
} from 'antd';
import { Card } from 'antd';
import { ExpandOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';
import {
  getWorkspaceGpuUtilization,
  type PromSampleValue,
} from '@/api/monitoring';
import { colorFor, lineSeriesDefaults } from '@/shared/ui/metrics/chartTheme';
import { useIsWsAdmin } from '../hooks/useIsWsAdmin';

const { Text } = Typography;

const DAY_OPTIONS = [1, 3, 7, 14, 21, 28];

interface Props {
  wsId: string;
}

/**
 * Workspace 占用 GPU 的时序图 (利用率 avg+max 双线 + 占用卡数阶梯线)。
 *
 * 仅 ws 管理员/超管可见: useIsWsAdmin 在渲染前判定, 非管理员直接 return null
 * (不挂载、不发请求、不闪现)。后端 GET /gpu-utilization 同样 assert_ws_admin 兜底。
 * 口径: avg/max/count(DCGM_FI_DEV_GPU_UTIL{namespace=...}), 分母 = 每时刻实际占用卡数。
 * 利用率长期贴 0 = 占卡空转 (浪费)。
 *
 * 顶部共享时间选择器 (1/3/7/14/21/28 天), 默认 7, 切换两图一起重拉。
 */
export default function WorkspaceGpuUtilChart({ wsId }: Props) {
  const { t } = useTranslation(['workspace']);
  const themeMode = useAppStore((s) => s.themeMode);
  const { canManage, loading: roleLoading } = useIsWsAdmin(wsId);

  const [days, setDays] = useState(7);
  const [data, setData] = useState<{
    avg: PromSampleValue[];
    max: PromSampleValue[];
    count: PromSampleValue[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!wsId || !canManage) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    getWorkspaceGpuUtilization(wsId, days)
      .then((res) => {
        if (cancelled) return;
        setData({ avg: res.avg, max: res.max, count: res.count });
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 403) return;
        setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [wsId, days, canManage]);

  const option = useMemo<EChartsOption>(() => {
    const toPoints = (vals: PromSampleValue[]) =>
      vals.map(([ts, v]) => [ts * 1000, Number(v)]);
    const avgColor = colorFor('gpu', 0);
    const maxColor = colorFor('memory', 1);
    const avgName = t('gpuUtil.avgUtil');
    const maxName = t('gpuUtil.peakUtil');
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${Number(v).toFixed(1)}%` },
      legend: { data: [avgName, maxName], top: 0 },
      grid: { left: 48, right: 16, top: 32, bottom: 28 },
      xAxis: {
        type: 'time',
        axisLabel: { formatter: (val: number) => dayjs(val).format('MM-DD HH:mm') },
      },
      yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
      series: [
        {
          ...lineSeriesDefaults(avgColor),
          name: avgName,
          data: toPoints(data?.avg ?? []),
        },
        {
          ...lineSeriesDefaults(maxColor),
          name: maxName,
          lineStyle: { type: 'dashed', color: maxColor },
          data: toPoints(data?.max ?? []),
        },
      ],
    };
  }, [data, themeMode, t]);

  const countOption = useMemo<EChartsOption>(() => {
    const toPoints = (vals: PromSampleValue[]) =>
      vals.map(([ts, v]) => [ts * 1000, Number(v)]);
    const countColor = colorFor('cpu', 2);
    const counts = (data?.count ?? []).map(([, v]) => Number(v));
    const yMax = counts.length ? Math.max(...counts) + 1 : 1;
    const countName = t('gpuUtil.seriesOccupied');
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', valueFormatter: (v) => t('gpuUtil.cardsValue', { count: Number(v) }) },
      legend: { data: [countName], top: 0 },
      grid: { left: 48, right: 16, top: 32, bottom: 28 },
      xAxis: {
        type: 'time',
        axisLabel: { formatter: (val: number) => dayjs(val).format('MM-DD HH:mm') },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: yMax,
        minInterval: 1,
        axisLabel: { formatter: '{value}' },
      },
      series: [
        {
          ...lineSeriesDefaults(countColor),
          name: countName,
          step: 'end',
          data: toPoints(data?.count ?? []),
        },
      ],
    };
  }, [data, themeMode, t]);

  // 放大 modal: 哪张图被放大 (null = 关) + 复用已加载的 option
  const [zoomed, setZoomed] = useState<null | 'util' | 'count'>(null);

  if (roleLoading || !canManage) return null;

  const hasUtil = (data?.avg?.length ?? 0) > 0 || (data?.max?.length ?? 0) > 0;
  const hasCount = (data?.count?.length ?? 0) > 0;

  const renderBody = (has: boolean, opt: EChartsOption, height = 220) => {
    if (loading) {
      return (
        <div style={{ textAlign: 'center', padding: `${Math.max(40, height / 4)}px 0` }}>
          <Spin />
        </div>
      );
    }
    if (err) return <Empty description={t('gpuUtil.loadFailed', { error: err })} />;
    if (!has) return <Empty description={t('gpuUtil.noData')} />;
    return <ReactECharts option={opt} style={{ height }} notMerge />;
  };

  // 子图标题栏: 标题 + 副标 + 放大 icon (副标解释口径, 替代原来塞在 body 里的灰字)
  const subHeader = (title: string, subtitle: string, key: 'util' | 'count') => (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 4,
      }}
    >
      <Space size={8} align="baseline">
        <Text strong style={{ fontSize: 13 }}>
          {title}
        </Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {subtitle}
        </Text>
      </Space>
      <Tooltip title={t('gpuUtil.zoom')}>
        <Button
          type="text"
          size="small"
          icon={<ExpandOutlined />}
          onClick={() => setZoomed(key)}
        />
      </Tooltip>
    </div>
  );

  return (
    <>
      <Card
        size="small"
        title={<span style={{ fontSize: 13 }}>{t('gpuUtil.title')}</span>}
        extra={
          <Space size={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t('gpuUtil.timeRange')}
            </Text>
            <Segmented
              size="small"
              value={days}
              onChange={(v) => setDays(Number(v))}
              options={DAY_OPTIONS.map((d) => ({ label: t('gpuUtil.dayOption', { count: d }), value: d }))}
            />
          </Space>
        }
        style={{ borderRadius: 8, marginTop: 12 }}
        bodyStyle={{ padding: 12 }}
        headStyle={{ padding: '0 12px', minHeight: 36 }}
      >
        <Row gutter={[12, 12]}>
          <Col xs={24} xl={12}>
            {subHeader(t('gpuUtil.utilTitle'), t('gpuUtil.utilSubtitle', { count: days }), 'util')}
            {renderBody(hasUtil, option)}
          </Col>
          <Col xs={24} xl={12}>
            {subHeader(
              t('gpuUtil.countTitle'),
              t('gpuUtil.countSubtitle', { count: days }),
              'count',
            )}
            {renderBody(hasCount, countOption)}
          </Col>
        </Row>
      </Card>

      {/* 放大 Modal · 单独全宽显示对应图表; 内置时间范围切换, 改完即时重拉 */}
      <Modal
        open={zoomed !== null}
        onCancel={() => setZoomed(null)}
        footer={null}
        width={1080}
        title={
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              paddingRight: 24,
            }}
          >
            <span>
              {zoomed === 'util' ? t('gpuUtil.utilTitle') : t('gpuUtil.countTitle')}
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 8, fontWeight: 'normal' }}>
                {t('gpuUtil.past', { count: days })}
              </Text>
            </span>
            <Space size={8}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('gpuUtil.timeRange')}
              </Text>
              <Segmented
                size="small"
                value={days}
                onChange={(v) => setDays(Number(v))}
                options={DAY_OPTIONS.map((d) => ({ label: t('gpuUtil.dayOption', { count: d }), value: d }))}
              />
            </Space>
          </div>
        }
        destroyOnClose
      >
        {zoomed === 'util' && renderBody(hasUtil, option, 480)}
        {zoomed === 'count' && renderBody(hasCount, countOption, 480)}
      </Modal>
    </>
  );
}
