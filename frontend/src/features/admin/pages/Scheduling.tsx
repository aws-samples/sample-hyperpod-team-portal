import { useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
  theme,
} from 'antd';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  PartitionOutlined,
  HourglassOutlined,
  ThunderboltOutlined,
  VerticalAlignTopOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { useAppStore } from '@/store';
import {
  MOCK_CLUSTER_QUEUES,
  MOCK_WORKLOADS,
  MOCK_PREEMPTION_EVENTS,
  MOCK_AVG_WAIT_TIME,
  type ClusterQueueMock,
  type JobType,
  type PreemptionEventMock,
  type WorkloadMock,
} from '@/mock/scheduling';
import {
  SEMANTIC_COLORS,
  baseLineOption,
  lineSeriesDefaults,
} from '@/shared/ui/metrics/chartTheme';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Text } = Typography;

/* ============================================================================
 * Admin Scheduling (M1 mock)
 *
 * Data contracts match the Kueue ClusterQueue / Workload CRD shapes so that
 * swapping in real backend data in M2 requires no UI changes — only the
 * datasource hook.
 *
 * M1 limitations (by design):
 *   - All mutation handlers are toast-only; no real PATCH to k8s.
 *   - No websocket / polling — static mock dataset per render.
 *   - "isAdmin" hard-coded `true` to demo the full admin surface.
 * ========================================================================== */

const PRIORITY_HIGH = 100;
const PRIORITY_LOW = 0;
const WAIT_WARN_MIN = 10;
const WAIT_DANGER_MIN = 30;

const JOB_TYPE_LABEL: Record<JobType, string> = {
  training: '训练',
  inference: '推理',
  dev: '开发',
};

const JOB_TYPE_COLOR: Record<JobType, string> = {
  training: 'geekblue',
  inference: 'purple',
  dev: 'cyan',
};

interface PriorityBucket {
  label: string;
  color: string;
}

const priorityBucket = (priority: number): PriorityBucket => {
  if (priority >= PRIORITY_HIGH) return { label: `high (${priority})`, color: 'red' };
  if (priority >= PRIORITY_LOW) return { label: `normal (${priority})`, color: 'blue' };
  return { label: `low (${priority})`, color: 'default' };
};

/* ---------------- ClusterQueue top card ---------------- */

interface ClusterQueueCardProps {
  cq: ClusterQueueMock;
  selected: boolean;
  onClick: () => void;
}

const ClusterQueueCard = ({ cq, selected, onClick }: ClusterQueueCardProps) => {
  const { token } = theme.useToken();
  const gpuPct =
    cq.total_gpu === 0 ? 0 : Math.round((cq.used_gpu / cq.total_gpu) * 100);
  const cpuPct =
    cq.total_cpu_millicores === 0
      ? 0
      : Math.round((cq.used_cpu_millicores / cq.total_cpu_millicores) * 100);
  const memPct =
    cq.total_memory_mib === 0
      ? 0
      : Math.round((cq.used_memory_mib / cq.total_memory_mib) * 100);

  const primary = cq.total_gpu > 0 ? gpuPct : cpuPct;

  return (
    <Card
      hoverable
      onClick={onClick}
      styles={{ body: { padding: 16 } }}
      style={{
        borderRadius: 12,
        height: '100%',
        borderColor: selected ? token.colorPrimary : undefined,
        borderWidth: selected ? 2 : 1,
        transition: 'border-color 120ms ease',
      }}
    >
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space size={6}>
            <Text strong style={{ fontSize: 14 }}>
              {cq.display_name}
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {cq.name}
            </Text>
          </Space>
          <Badge
            status={cq.pending_workloads > 0 ? 'warning' : 'success'}
            text={cq.pending_workloads > 0 ? `${cq.pending_workloads} 排队` : 'OK'}
          />
        </Space>

        {cq.cohort && (
          <Tag color="blue" style={{ alignSelf: 'flex-start' }}>
            cohort: {cq.cohort}
          </Tag>
        )}

        {cq.total_gpu > 0 && (
          <div>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                GPU
              </Text>
              <Text strong style={{ fontSize: 12 }}>
                {cq.used_gpu} / {cq.total_gpu}
              </Text>
            </Space>
            <Progress
              percent={gpuPct}
              size="small"
              showInfo={false}
              strokeColor={token.colorPrimary}
            />
          </div>
        )}

        <div>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              CPU
            </Text>
            <Text strong style={{ fontSize: 12 }}>
              {(cq.used_cpu_millicores / 1000).toFixed(0)} /{' '}
              {(cq.total_cpu_millicores / 1000).toFixed(0)} c
            </Text>
          </Space>
          <Progress percent={cpuPct} size="small" showInfo={false} />
        </div>

        <div>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Memory
            </Text>
            <Text strong style={{ fontSize: 12 }}>
              {(cq.used_memory_mib / 1024).toFixed(0)} /{' '}
              {(cq.total_memory_mib / 1024).toFixed(0)} GiB
            </Text>
          </Space>
          <Progress
            percent={memPct}
            size="small"
            showInfo={false}
            strokeColor={SEMANTIC_COLORS.memory}
          />
        </div>

        <Space size={6} wrap>
          <Tag color="processing">运行 {cq.admitted_workloads}</Tag>
          <Tag color="warning">排队 {cq.pending_workloads}</Tag>
          <Tag color="default">{cq.preemption_policy}</Tag>
        </Space>

        {primary >= 90 && (
          <Alert
            type="error"
            showIcon
            banner
            message={<span style={{ fontSize: 11 }}>容量濒临饱和</span>}
            style={{ padding: '2px 8px' }}
          />
        )}
      </Space>
    </Card>
  );
};

/* ---------------- Priority Badge ---------------- */

const PriorityBadge = ({ priority }: { priority: number }) => {
  const { label, color } = priorityBucket(priority);
  return <Tag color={color}>{label}</Tag>;
};

/* ---------------- Wait Duration cell ---------------- */

const WaitDurationCell = ({ pendingSince }: { pendingSince: string }) => {
  const { token } = theme.useToken();
  const minutes = Math.max(0, dayjs().diff(dayjs(pendingSince), 'minute'));
  const color =
    minutes >= WAIT_DANGER_MIN
      ? token.colorError
      : minutes >= WAIT_WARN_MIN
      ? token.colorWarning
      : token.colorTextSecondary;
  const label =
    minutes < 60
      ? `${minutes}m`
      : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return (
    <Space size={4}>
      <ClockCircleOutlined style={{ color }} />
      <Text style={{ color, fontVariantNumeric: 'tabular-nums' }}>{label}</Text>
    </Space>
  );
};

/* ---------------- Preemption Timeline ---------------- */

const PreemptionTimeline = ({ events }: { events: PreemptionEventMock[] }) => {
  if (events.length === 0) {
    return <Empty description="近期无抢占事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const sorted = [...events].sort((a, b) =>
    dayjs(b.occurred_at).valueOf() - dayjs(a.occurred_at).valueOf(),
  );
  return (
    <Timeline
      style={{ marginTop: 8 }}
      items={sorted.slice(0, 10).map((ev) => ({
        color: ev.severity === 'high-priority' ? 'red' : 'orange',
        children: (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Text style={{ fontSize: 12 }}>
              <Text strong>{ev.preempting_workload}</Text>{' '}
              <Text type="secondary">抢占</Text>{' '}
              <Text strong>{ev.preempted_workload}</Text>
            </Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {ev.reason}
            </Text>
            <Space size={8}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {dayjs(ev.occurred_at).fromNow()}
              </Text>
              {ev.gpu_freed > 0 && (
                <Tag color="geekblue" style={{ fontSize: 11, marginInlineEnd: 0 }}>
                  释放 {ev.gpu_freed} GPU
                </Tag>
              )}
            </Space>
          </Space>
        ),
      }))}
    />
  );
};

/* ---------------- Avg Wait Chart ---------------- */

const AvgWaitChart = ({ data }: { data: typeof MOCK_AVG_WAIT_TIME }) => {
  const themeMode = useAppStore((s) => s.themeMode);

  const option = useMemo<EChartsOption>(() => {
    const training: [string, number][] = data.map((d) => [d.hour, d.training_minutes]);
    const inference: [string, number][] = data.map((d) => [d.hour, d.inference_minutes]);
    const base = baseLineOption('min', ['训练', '推理'], themeMode);
    return {
      ...base,
      xAxis: {
        ...base.xAxis,
        type: 'time',
      },
      yAxis: {
        ...base.yAxis,
        min: 0,
      },
      series: [
        {
          ...lineSeriesDefaults(SEMANTIC_COLORS.gpu),
          name: '训练',
          data: training,
        },
        {
          ...lineSeriesDefaults(SEMANTIC_COLORS.itl),
          name: '推理',
          data: inference,
        },
      ],
    };
  }, [data, themeMode]);

  return (
    <ReactECharts
      option={option}
      style={{ height: 220, width: '100%' }}
      notMerge
      lazyUpdate
    />
  );
};

/* ============================================================================
 * Main page
 * ========================================================================== */

// M1: hard-code admin view to exercise the full operator surface in demos.
// M2 will bind this to the RBAC claim from /users/me.
const IS_ADMIN = true;

type JobTypeFilter = 'all' | JobType;
type PriorityFilter = 'all' | 'high' | 'normal' | 'low';

export default function AdminScheduling() {
  const { token } = theme.useToken();

  const [selectedCq, setSelectedCq] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<JobTypeFilter>('all');
  const [filterPriority, setFilterPriority] = useState<PriorityFilter>('all');
  const [filterWorkspace, setFilterWorkspace] = useState<string>('all');

  /* ---------------- Derived data ---------------- */

  const workspaceOptions = useMemo(() => {
    const set = new Set(MOCK_WORKLOADS.map((w) => w.workspace_name));
    return Array.from(set).sort();
  }, []);

  const filteredWorkloads = useMemo<WorkloadMock[]>(() => {
    return MOCK_WORKLOADS.filter((w) => {
      if (selectedCq && w.cluster_queue_id !== selectedCq) return false;
      if (filterType !== 'all' && w.job_type !== filterType) return false;
      if (filterWorkspace !== 'all' && w.workspace_name !== filterWorkspace) return false;
      if (filterPriority !== 'all') {
        const b = priorityBucket(w.priority).label.split(' ')[0];
        if (b !== filterPriority) return false;
      }
      return true;
    }).sort((a, b) => {
      if (b.priority !== a.priority) return b.priority - a.priority;
      return dayjs(a.pending_since).valueOf() - dayjs(b.pending_since).valueOf();
    });
  }, [selectedCq, filterType, filterPriority, filterWorkspace]);

  const kpi = useMemo(() => {
    const trainingWorkloads = MOCK_WORKLOADS.filter((w) => w.job_type === 'training');
    const inferenceWorkloads = MOCK_WORKLOADS.filter((w) => w.job_type === 'inference');
    const minutesSince = (w: WorkloadMock): number =>
      Math.max(0, dayjs().diff(dayjs(w.pending_since), 'minute'));
    const avg = (xs: number[]): number =>
      xs.length === 0 ? 0 : xs.reduce((a, b) => a + b, 0) / xs.length;
    return {
      queues: MOCK_CLUSTER_QUEUES.length,
      pending: MOCK_WORKLOADS.length,
      running: MOCK_CLUSTER_QUEUES.reduce((a, q) => a + q.admitted_workloads, 0),
      avgWaitTraining: avg(trainingWorkloads.map(minutesSince)),
      avgWaitInference: avg(inferenceWorkloads.map(minutesSince)),
    };
  }, []);

  /* ---------------- Admin action handlers (toast-only for M1) ---------------- */

  const requireAdmin = (): boolean => {
    if (!IS_ADMIN) {
      message.warning('仅管理员可操作');
      return false;
    }
    return true;
  };

  const handleBoost = (w: WorkloadMock) => {
    if (!requireAdmin()) return;
    message.success(
      `已提升 ${w.workload_name} 优先级 +10(mock · priority=${w.priority + 10})`,
    );
  };

  const handleDemote = (w: WorkloadMock) => {
    if (!requireAdmin()) return;
    message.success(
      `已降低 ${w.workload_name} 优先级 -10(mock · priority=${w.priority - 10})`,
    );
  };

  const handleMoveToTop = (w: WorkloadMock) => {
    if (!requireAdmin()) return;
    message.success(`已置顶 ${w.workload_name}(mock · priority=999)`);
  };

  const handleCancel = (w: WorkloadMock) => {
    if (!requireAdmin()) return;
    Modal.confirm({
      title: `取消任务 ${w.workload_name}?`,
      content: '任务将从队列移除,已分配资源立即回收。此操作不可恢复。',
      okText: '确认取消',
      okType: 'danger',
      cancelText: '关闭',
      onOk: () => {
        message.success(`已从队列移除 ${w.workload_name}(mock)`);
      },
    });
  };

  /* ---------------- Table columns ---------------- */

  const columns: ProColumns<WorkloadMock>[] = [
    {
      title: '#',
      width: 48,
      render: (_, __, index) => (
        <Text type="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {index + 1}
        </Text>
      ),
    },
    {
      title: '队列',
      dataIndex: 'cluster_queue_id',
      width: 140,
      render: (_, row) => {
        const cq = MOCK_CLUSTER_QUEUES.find((q) => q.id === row.cluster_queue_id);
        return <Tag color="cyan">{cq?.name ?? row.cluster_queue_id}</Tag>;
      },
    },
    {
      title: '任务',
      dataIndex: 'workload_name',
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ fontSize: 13 }}>
            {row.workload_name}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {row.workspace_name}
          </Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'job_type',
      width: 80,
      render: (_, row) => (
        <Tag color={JOB_TYPE_COLOR[row.job_type]}>{JOB_TYPE_LABEL[row.job_type]}</Tag>
      ),
    },
    {
      title: '创建人',
      dataIndex: 'creator_display_name',
      width: 120,
    },
    {
      title: '请求资源',
      width: 180,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          {row.req_gpu > 0 ? (
            <Tag color="geekblue" icon={<ThunderboltOutlined />} style={{ marginInlineEnd: 0 }}>
              {row.req_gpu} × {row.req_gpu_type ?? 'GPU'}
            </Tag>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              CPU only
            </Text>
          )}
          <Text type="secondary" style={{ fontSize: 11 }}>
            {(row.req_cpu_millicores / 1000).toFixed(0)}c /{' '}
            {(row.req_memory_mib / 1024).toFixed(0)} GiB
          </Text>
        </Space>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 120,
      render: (_, row) => <PriorityBadge priority={row.priority} />,
    },
    {
      title: '已等待',
      dataIndex: 'pending_since',
      width: 110,
      render: (_, row) => <WaitDurationCell pendingSince={row.pending_since} />,
    },
    {
      title: '操作',
      width: 180,
      fixed: 'right',
      render: (_, row) => {
        const disabledTip = IS_ADMIN ? undefined : '仅管理员可操作';
        return (
          <Space size={4}>
            <Tooltip title={disabledTip ?? '优先级 +10'}>
              <Button
                size="small"
                icon={<ArrowUpOutlined />}
                disabled={!IS_ADMIN}
                onClick={() => handleBoost(row)}
              />
            </Tooltip>
            <Popconfirm
              title="置顶任务"
              description={`将 ${row.workload_name} priority 设为 999(当前队列最高)?`}
              onConfirm={() => handleMoveToTop(row)}
              okText="置顶"
              cancelText="取消"
              disabled={!IS_ADMIN}
            >
              <Tooltip title={disabledTip ?? '置顶'}>
                <Button
                  size="small"
                  type="primary"
                  icon={<VerticalAlignTopOutlined />}
                  disabled={!IS_ADMIN}
                />
              </Tooltip>
            </Popconfirm>
            <Tooltip title={disabledTip ?? '优先级 -10'}>
              <Button
                size="small"
                icon={<ArrowDownOutlined />}
                disabled={!IS_ADMIN}
                onClick={() => handleDemote(row)}
              />
            </Tooltip>
            <Tooltip title={disabledTip ?? '取消任务'}>
              <Button
                size="small"
                danger
                icon={<CloseCircleOutlined />}
                disabled={!IS_ADMIN}
                onClick={() => handleCancel(row)}
              />
            </Tooltip>
          </Space>
        );
      },
    },
  ];

  /* ---------------- Render ---------------- */

  return (
    <PageContainer
      title="调度队列"
      subTitle="Kueue-based scheduling · M1 mock 演示"
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="M1 Mock 数据 · M2 将接入 Kueue ClusterQueue / Workload 真 CRD,按钮操作 PATCH k8s spec.priority"
      />

      {/* 顶部 KPI Row */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={8} xl={5}>
          <Card styles={{ body: { padding: 16 } }}>
            <Statistic
              title="总队列"
              value={kpi.queues}
              prefix={<PartitionOutlined style={{ color: token.colorPrimary }} />}
            />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={5}>
          <Card styles={{ body: { padding: 16 } }}>
            <Statistic
              title="排队中"
              value={kpi.pending}
              prefix={<HourglassOutlined style={{ color: token.colorWarning }} />}
              valueStyle={{ color: token.colorWarning }}
            />
          </Card>
        </Col>
        <Col xs={12} md={8} xl={4}>
          <Card styles={{ body: { padding: 16 } }}>
            <Statistic
              title="运行中"
              value={kpi.running}
              valueStyle={{ color: token.colorSuccess }}
            />
          </Card>
        </Col>
        <Col xs={12} md={12} xl={5}>
          <Card styles={{ body: { padding: 16 } }}>
            <Statistic
              title="平均等待 · 训练"
              value={kpi.avgWaitTraining}
              precision={1}
              suffix="min"
            />
          </Card>
        </Col>
        <Col xs={12} md={12} xl={5}>
          <Card styles={{ body: { padding: 16 } }}>
            <Statistic
              title="平均等待 · 推理"
              value={kpi.avgWaitInference}
              precision={1}
              suffix="min"
            />
          </Card>
        </Col>
      </Row>

      {/* ClusterQueue 卡片栏 */}
      <Typography.Title level={5}>ClusterQueue</Typography.Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {MOCK_CLUSTER_QUEUES.map((cq) => (
          <Col key={cq.id} xs={24} md={12} xl={8}>
            <ClusterQueueCard
              cq={cq}
              selected={selectedCq === cq.id}
              onClick={() => setSelectedCq((prev) => (prev === cq.id ? null : cq.id))}
            />
          </Col>
        ))}
      </Row>

      {/* 主表格 + 侧栏 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={16}>
          <Card
            title="当前排队任务"
            extra={
              <Space wrap>
                <Select
                  size="small"
                  value={selectedCq ?? 'all'}
                  style={{ width: 160 }}
                  onChange={(v) => setSelectedCq(v === 'all' ? null : v)}
                  options={[
                    { value: 'all', label: '全部队列' },
                    ...MOCK_CLUSTER_QUEUES.map((q) => ({
                      value: q.id,
                      label: q.name,
                    })),
                  ]}
                />
                <Select
                  size="small"
                  value={filterType}
                  style={{ width: 120 }}
                  onChange={setFilterType}
                  options={[
                    { value: 'all', label: '全部类型' },
                    { value: 'training', label: '训练' },
                    { value: 'inference', label: '推理' },
                    { value: 'dev', label: '开发' },
                  ]}
                />
                <Select
                  size="small"
                  value={filterPriority}
                  style={{ width: 140 }}
                  onChange={setFilterPriority}
                  options={[
                    { value: 'all', label: '全部优先级' },
                    { value: 'high', label: 'high (≥100)' },
                    { value: 'normal', label: 'normal (0-99)' },
                    { value: 'low', label: 'low (<0)' },
                  ]}
                />
                <Select
                  size="small"
                  value={filterWorkspace}
                  style={{ width: 160 }}
                  onChange={setFilterWorkspace}
                  options={[
                    { value: 'all', label: '全部 Workspace' },
                    ...workspaceOptions.map((w) => ({ value: w, label: w })),
                  ]}
                />
              </Space>
            }
            styles={{ body: { padding: 0 } }}
          >
            <ProTable<WorkloadMock>
              columns={columns}
              dataSource={filteredWorkloads}
              rowKey="id"
              search={false}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              toolBarRender={false}
              scroll={{ x: 1100 }}
              options={false}
              locale={{ emptyText: <Empty description="当前过滤条件下无排队任务" /> }}
            />
          </Card>
        </Col>

        <Col xs={24} xl={8}>
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card title="抢占事件" styles={{ body: { paddingBottom: 8 } }}>
              <PreemptionTimeline events={MOCK_PREEMPTION_EVENTS} />
            </Card>
            <Card title="平均等待趋势 · 近 24h" styles={{ body: { padding: 12 } }}>
              <AvgWaitChart data={MOCK_AVG_WAIT_TIME} />
            </Card>
          </Space>
        </Col>
      </Row>
    </PageContainer>
  );
}
