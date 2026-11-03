import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Col, Collapse, Dropdown, Radio, Row, Space, Tag, Tooltip, Typography } from 'antd';
import { SettingOutlined } from '@ant-design/icons';
import { ProCard } from '@ant-design/pro-components';
import { useTranslation } from 'react-i18next';
import type { MetricDimension, QueryTemplate } from '@/api/monitoring';
import PromRangeChart from './PromRangeChart';

const { Text } = Typography;

interface Props {
  /** Fetcher that returns resolved templates (vars substituted). */
  loadTemplates: () => Promise<QueryTemplate[]>;
  /** Trigger re-fetch when this changes (e.g. job id). */
  depKey: string;
  /** Chart height. Training = 240 (6 grid), DevInstance = 220 (4 grid). */
  height?: number;
  /** Info banner at top (optional). */
  banner?: React.ReactNode;
  /**
   * 显示 Job / Pod / GPUCard 三维度切换. 训练任务详情打开,
   * 开发机不打开 (开发机只有单维度).
   */
  showDimensionSwitch?: boolean;
}

const DIMENSION_OPTIONS: { label: string; value: MetricDimension }[] = [
  { label: 'Job', value: 'job' },
  { label: 'Pod', value: 'pod' },
  { label: 'GPUCard', value: 'gpu_card' },
];

const RANGE_OPTIONS = [
  { label: '15m', value: 15 },
  { label: '1h', value: 60 },
  { label: '6h', value: 360 },
  { label: '24h', value: 1440 },
];

// 刷新频率选项: 秒数原样显示, 0 = 暂停 (存 monitoring ns 的 key, 渲染时再 t())
const REFRESH_OPTIONS: { value: number; label?: string; labelKey?: 'tabPanel.refreshPaused' }[] = [
  { label: '10s', value: 10 },
  { label: '30s', value: 30 },
  { labelKey: 'tabPanel.refreshPaused', value: 0 },
];

// 折叠组展示顺序 (按后端 group_key slug; GPU 优先, 网络/资源在后, 训练/队列收尾); 未列的组排末尾
const GROUP_ORDER = [
  'gpu', 'gpu_perf', 'gpu_health', 'gpu_clock_power', 'gpu_memory', 'gpu_nvlink',
  'node_resources', 'cpu', 'memory', 'disk', 'network', 'efa', 'process',
  'status', 'training', 'inference',
  'sglang_latency', 'sglang_throughput', 'sglang_kv_cache', 'sglang_queue', 'sglang',
  'dynamo_latency', 'dynamo_throughput', 'dynamo_kv_cache', 'dynamo_queue',
];

const groupRank = (g: string): number => {
  const i = GROUP_ORDER.indexOf(g);
  return i === -1 ? GROUP_ORDER.length : i;
};

/**
 * Generic monitoring tab shell: range + refresh pickers + responsive grid
 * of PromRangeCharts. Used by Training Detail and DevInstance Detail.
 */
export default function MonitoringTabPanel({
  loadTemplates,
  depKey,
  height = 240,
  banner,
  showDimensionSwitch = false,
}: Props) {
  const { t } = useTranslation('monitoring');
  const [templates, setTemplates] = useState<QueryTemplate[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [rangeMinutes, setRangeMinutes] = useState(15);
  const [refreshSec, setRefreshSec] = useState(30);
  const [dimension, setDimension] = useState<MetricDimension>('job');
  // 用户隐藏的指标 key 集合 · 默全显
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set());
  // 当前展开的折叠组 · 默认全收起 (antd Collapse 懒渲染, 收起组的图不挂载/不请求 → 进 tab 秒显分组结构)
  const [activeGroups, setActiveGroups] = useState<string[]>([]);

  // 当前维度下所有候选指标 (供 dropdown checkbox 列表)
  const dimensionTemplates = useMemo(() => {
    if (!templates) return [];
    if (!showDimensionSwitch) return templates;
    return templates.filter((tpl) => (tpl.dimension ?? 'job') === dimension);
  }, [templates, showDimensionSwitch, dimension]);

  // 实际渲染的图 = 当前维度内 - 用户隐藏的
  const visibleTemplates = useMemo(
    () => dimensionTemplates.filter((tpl) => !hiddenKeys.has(tpl.key)),
    [dimensionTemplates, hiddenKeys],
  );

  // 按 group_key (稳定 slug) 折叠分组并排序; 展示名用后端按语言填好的 group; 都没有归"其他"
  const grouped = useMemo(() => {
    const m = new Map<string, { label: string; items: QueryTemplate[] }>();
    for (const tpl of visibleTemplates) {
      // 版本错位兜底: 旧后端无 group_key 时退回按 group 展示名分组
      const key = tpl.group_key || tpl.group || '__other__';
      const entry = m.get(key) ?? m.set(key, { label: tpl.group || '', items: [] }).get(key)!;
      entry.items.push(tpl);
    }
    return [...m.entries()].sort((a, b) => groupRank(a[0]) - groupRank(b[0]));
  }, [visibleTemplates]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setErr(null);
      try {
        const list = await loadTemplates();
        if (!cancelled) setTemplates(list);
      } catch (e) {
        if (!cancelled) setErr((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [depKey]);

  return (
    <div>
      {banner}
      <Space style={{ marginBottom: 16 }} size="large" wrap>
        {showDimensionSwitch && (
          <Space>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {t('tabPanel.dimension')}
            </Text>
            <Radio.Group
              value={dimension}
              onChange={(e) => setDimension(e.target.value as MetricDimension)}
              options={DIMENSION_OPTIONS}
              optionType="button"
              buttonStyle="solid"
              size="small"
            />
          </Space>
        )}
        <Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('tabPanel.timeRange')}
          </Text>
          <Radio.Group
            value={rangeMinutes}
            onChange={(e) => setRangeMinutes(e.target.value)}
            options={RANGE_OPTIONS}
            optionType="button"
            buttonStyle="solid"
            size="small"
          />
        </Space>
        <Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            {t('tabPanel.refreshInterval')}
          </Text>
          <Radio.Group
            value={refreshSec}
            onChange={(e) => setRefreshSec(e.target.value)}
            options={REFRESH_OPTIONS.map((o) => ({
              value: o.value,
              label: o.labelKey ? t(o.labelKey) : o.label,
            }))}
            optionType="button"
            buttonStyle="solid"
            size="small"
          />
        </Space>

        {/* 指标筛选: 复选框列表, 当前维度全候选, 默全选, 取消勾隐藏 */}
        <Dropdown
          trigger={['click']}
          placement="bottomRight"
          dropdownRender={() => (
            <div
              style={{
                background: '#fff',
                padding: 12,
                border: '1px solid #f0f0f0',
                borderRadius: 6,
                maxHeight: 400,
                overflowY: 'auto',
                minWidth: 280,
                boxShadow: '0 6px 16px rgba(0,0,0,0.08)',
              }}
            >
              <Space style={{ marginBottom: 8 }} size="small">
                <Button
                  size="small"
                  onClick={() => setHiddenKeys(new Set())}
                >
                  {t('tabPanel.filter.selectAll')}
                </Button>
                <Button
                  size="small"
                  onClick={() =>
                    setHiddenKeys(new Set(dimensionTemplates.map((tpl) => tpl.key)))
                  }
                >
                  {t('tabPanel.filter.selectNone')}
                </Button>
              </Space>
              <div>
                {dimensionTemplates.map((tpl) => (
                  <Tooltip
                    key={tpl.key}
                    placement="left"
                    title={
                      <div style={{ maxWidth: 360, fontSize: 13, lineHeight: 1.6 }}>
                        {/* 不写死颜色: tooltip 底色由主题决定 (浅色白底 / 深色 #1f1f1f),
                            靠继承 + opacity 分层, 两种主题都看得清 */}
                        <div style={{ marginBottom: 6 }}>
                          <Text strong style={{ fontSize: 14 }}>
                            {tpl.title}
                          </Text>
                          <Text style={{ marginLeft: 8, fontSize: 12, opacity: 0.65 }}>
                            {t('tabPanel.filter.unit', { unit: tpl.unit })}
                          </Text>
                        </div>
                        <div style={{ whiteSpace: 'pre-wrap', opacity: 0.88 }}>
                          {tpl.description || t('tabPanel.filter.noDescription')}
                        </div>
                      </div>
                    }
                  >
                    <div style={{ padding: '4px 0' }}>
                      <Checkbox
                        checked={!hiddenKeys.has(tpl.key)}
                        onChange={(e) => {
                          setHiddenKeys((prev) => {
                            const next = new Set(prev);
                            if (e.target.checked) next.delete(tpl.key);
                            else next.add(tpl.key);
                            return next;
                          });
                        }}
                      >
                        {tpl.title}{' '}
                        <Tag color="default" style={{ fontSize: 10 }}>
                          {tpl.unit}
                        </Tag>
                      </Checkbox>
                    </div>
                  </Tooltip>
                ))}
              </div>
            </div>
          )}
        >
          <Button size="small" icon={<SettingOutlined />}>
            {t('tabPanel.filter.button', {
              visible: visibleTemplates.length,
              total: dimensionTemplates.length,
            })}
          </Button>
        </Dropdown>
      </Space>

      {err && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('tabPanel.loadFailed', { error: err })}
        />
      )}

      {templates && visibleTemplates.length === 0 && (
        <Alert
          type="info"
          showIcon
          message={
            dimensionTemplates.length === 0
              ? t('tabPanel.emptyDimension')
              : t('tabPanel.allHidden')
          }
        />
      )}

      <Collapse
        activeKey={activeGroups}
        onChange={(k) => setActiveGroups(k as string[])}
        items={grouped.map(([key, { label, items }]) => ({
          key,
          label: (
            <Space size={6}>
              <Text strong>{label || t('group.other')}</Text>
              <Tag color="default" style={{ fontSize: 11 }}>
                {items.length}
              </Tag>
            </Space>
          ),
          children: (
            <Row gutter={[16, 16]}>
              {items.map((tpl) => (
                <Col key={tpl.key} xs={24} md={12} xl={8}>
                  <ProCard
                    // 标题去掉模板自带的 "(单位)" 后缀, 单位统一由 subTitle 显示一次 (避免 "吞吐 (tokens/s) tokens/s" 重复)
                    title={tpl.title.replace(/\s*[（(][^（()）]*[)）]\s*$/, '')}
                    subTitle={
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {tpl.unit}
                      </Text>
                    }
                    bordered
                    bodyStyle={{ padding: 8 }}
                    headerBordered
                  >
                    <PromRangeChart
                      template={tpl}
                      rangeMinutes={rangeMinutes}
                      refreshSec={refreshSec}
                      height={height}
                    />
                  </ProCard>
                </Col>
              ))}
            </Row>
          ),
        }))}
      />
    </div>
  );
}
