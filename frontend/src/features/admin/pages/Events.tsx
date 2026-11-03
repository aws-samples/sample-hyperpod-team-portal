import { useMemo, useState } from 'react';
import {
  Badge,
  DatePicker,
  Select,
  Space,
  Tag,
  Timeline,
  Typography,
  theme,
} from 'antd';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  ApartmentOutlined,
  AppstoreAddOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  FileSyncOutlined,
  InfoCircleOutlined,
  SwapOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';
import {
  mockOpsEvents,
  type EventKind,
  type EventSeverity,
  type OpsEvent,
} from '@/mock/infra';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Text } = Typography;
const { RangePicker } = DatePicker;

const KIND_META: Record<EventKind, { label: string; icon: React.ReactNode }> = {
  'node-failure': { label: '节点故障', icon: <CloudServerOutlined /> },
  'node-replaced': { label: '节点替换', icon: <SwapOutlined /> },
  'cluster-upgrade': { label: '集群升级', icon: <FileSyncOutlined /> },
  'quota-change': { label: '配额变更', icon: <AppstoreAddOutlined /> },
  'queue-preempt': { label: '队列抢占', icon: <ThunderboltOutlined /> },
  'addon-update': { label: 'Addon 升级', icon: <ApartmentOutlined /> },
  scale: { label: '扩缩容', icon: <SwapOutlined /> },
};

export default function AdminEvents() {
  const { token } = theme.useToken();
  const [kinds, setKinds] = useState<EventKind[]>([]);
  const [severities, setSeverities] = useState<EventSeverity[]>([]);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);

  const filtered = useMemo(() => {
    return mockOpsEvents.filter((e) => {
      if (kinds.length > 0 && !kinds.includes(e.kind)) return false;
      if (severities.length > 0 && !severities.includes(e.severity)) return false;
      if (range && range[0] && range[1]) {
        const ts = dayjs(e.ts);
        if (ts.isBefore(range[0]) || ts.isAfter(range[1])) return false;
      }
      return true;
    });
  }, [kinds, severities, range]);

  const colorOf = (sev: EventSeverity): string => {
    if (sev === 'error') return token.colorError;
    if (sev === 'warning') return token.colorWarning;
    return token.colorInfo;
  };

  const iconOf = (e: OpsEvent) => {
    const base = KIND_META[e.kind].icon;
    return (
      <span style={{ color: colorOf(e.severity) }}>
        {e.severity === 'info' && e.kind === 'node-replaced'
          ? <CheckCircleOutlined />
          : e.severity === 'error'
          ? <WarningOutlined />
          : e.severity === 'info'
          ? <InfoCircleOutlined />
          : base}
      </span>
    );
  };

  return (
    <PageContainer
      title="运维事件"
      subTitle="HealthMonitoring / Kueue / Cluster Manager 的关键事件流"
      extra={[
        <Select
          key="kind"
          mode="multiple"
          allowClear
          placeholder="事件类型"
          style={{ minWidth: 180 }}
          value={kinds}
          onChange={(v) => setKinds(v as EventKind[])}
          options={Object.entries(KIND_META).map(([k, v]) => ({
            value: k,
            label: v.label,
          }))}
        />,
        <Select
          key="sev"
          mode="multiple"
          allowClear
          placeholder="严重等级"
          style={{ minWidth: 140 }}
          value={severities}
          onChange={(v) => setSeverities(v as EventSeverity[])}
          options={[
            { value: 'error', label: 'Error' },
            { value: 'warning', label: 'Warning' },
            { value: 'info', label: 'Info' },
          ]}
        />,
        <RangePicker
          key="range"
          showTime
          value={range as never}
          onChange={(v) => setRange(v as [Dayjs, Dayjs] | null)}
        />,
      ]}
    >
      <ProCard
        bordered={false}
        title={`事件列表 (${filtered.length})`}
        headerBordered
        style={{ borderRadius: 12 }}
      >
        <Timeline
          mode="left"
          items={filtered.map((e) => ({
            dot: iconOf(e),
            color: colorOf(e.severity),
            children: (
              <Space
                direction="vertical"
                size={2}
                style={{ width: '100%', paddingBottom: 8 }}
              >
                <Space size={8} wrap>
                  <Text strong>{e.title}</Text>
                  <Tag
                    color={
                      e.severity === 'error'
                        ? 'error'
                        : e.severity === 'warning'
                        ? 'warning'
                        : 'blue'
                    }
                    style={{ fontSize: 11 }}
                  >
                    {e.severity.toUpperCase()}
                  </Tag>
                  <Tag color="default" style={{ fontSize: 11 }}>
                    {KIND_META[e.kind].label}
                  </Tag>
                  <Badge
                    status="default"
                    text={
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {e.source}
                      </Text>
                    }
                  />
                </Space>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {e.detail}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {dayjs(e.ts).format('YYYY-MM-DD HH:mm:ss')} ·{' '}
                  {dayjs(e.ts).fromNow()}
                  {e.targetId ? ` · target ${e.targetId}` : ''}
                </Text>
              </Space>
            ),
          }))}
        />
      </ProCard>
    </PageContainer>
  );
}
