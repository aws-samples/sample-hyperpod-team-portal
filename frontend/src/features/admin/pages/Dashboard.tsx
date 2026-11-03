import { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  List,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  theme,
} from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import {
  AlertOutlined,
  ArrowUpOutlined,
  CheckCircleOutlined,
  CloudServerOutlined,
  DollarOutlined,
  ExclamationCircleOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';
import { mockWorkspaces } from '@/mock/workspaces';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Text } = Typography;

type AlertLevel = 'error' | 'warning' | 'info';

interface AdminAlert {
  ts: number;
  level: AlertLevel;
  message: string;
  source: string;
}

const ADMIN_ALERTS: AdminAlert[] = [
  {
    ts: Date.now() - 2 * 60_000,
    level: 'error',
    message: 'team-a-nlp 集群 GPU 配额即将爆表 (98%)',
    source: 'Quota Controller',
  },
  {
    ts: Date.now() - 15 * 60_000,
    level: 'warning',
    message: 'Aurora Postgres CPU >80% 持续 10min',
    source: 'RDS Monitor',
  },
  {
    ts: Date.now() - 42 * 60_000,
    level: 'warning',
    message: 'llama3-sft rank-3 NCCL slow all-reduce',
    source: 'Training Operator',
  },
  {
    ts: Date.now() - 90 * 60_000,
    level: 'error',
    message: 'vllm-qwen72b OOM 重启 x3',
    source: 'Inference Controller',
  },
  {
    ts: Date.now() - 3 * 3600_000,
    level: 'info',
    message: 'S3 日志成本本月超过 ¥230 基线',
    source: 'Cost Explorer',
  },
];

interface FailedNode {
  id: string;
  zone: string;
  reason: string;
  since: string;
}

const FAILED_NODES: FailedNode[] = [
  {
    id: 'ip-10-0-3-42.ec2.internal',
    zone: 'us-west-2a',
    reason: 'GPU ECC 错误 (H100 / GPU0)',
    since: dayjs().subtract(34, 'minute').toISOString(),
  },
  {
    id: 'ip-10-0-2-18.ec2.internal',
    zone: 'us-west-2b',
    reason: 'NotReady - kubelet 不响应',
    since: dayjs().subtract(2, 'hour').toISOString(),
  },
];

export default function AdminDashboard() {
  const { token } = theme.useToken();
  const [timeRange, setTimeRange] = useState<'today' | 'week' | 'month'>(
    'today',
  );

  /** Top-workspace resource ranking (by quotaGpu as proxy for usage). */
  const rankingOption = useMemo<EChartsOption>(() => {
    const sorted = [...mockWorkspaces].sort((a, b) => b.usedGpu - a.usedGpu);
    return {
      grid: { left: 120, right: 80, top: 12, bottom: 32 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (params: unknown) => {
          const arr = params as Array<{ name: string; value: number }>;
          const p = arr[0];
          if (!p) return '';
          return `${p.name}<br/>GPU 使用: ${p.value} 卡`;
        },
      },
      xAxis: {
        type: 'value',
        splitLine: { lineStyle: { type: 'dashed' } },
        name: 'GPU · 卡',
      },
      yAxis: {
        type: 'category',
        data: sorted.map((w) => w.displayName),
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: sorted.map((w) => ({
            value: w.usedGpu,
            itemStyle: {
              color:
                w.usedGpu / w.quotaGpu > 0.85
                  ? token.colorError
                  : w.usedGpu / w.quotaGpu > 0.6
                  ? token.colorWarning
                  : token.colorPrimary,
              borderRadius: [0, 4, 4, 0],
            },
          })),
          barWidth: 18,
          label: { show: true, position: 'right', formatter: '{c} 卡' },
        },
      ],
    };
  }, [token]);

  /** Cost trend — past 30 days, stacked by training / inference / dev. */
  const costTrendOption = useMemo<EChartsOption>(() => {
    const days: string[] = [];
    const training: number[] = [];
    const inference: number[] = [];
    const dev: number[] = [];
    for (let i = 29; i >= 0; i -= 1) {
      days.push(dayjs().subtract(i, 'day').format('MM-DD'));
      const base = 2400 + Math.sin(i / 3) * 400;
      training.push(Math.round(base + 800 + (i * 37) % 500));
      inference.push(Math.round(800 + (i * 19) % 300));
      dev.push(Math.round(450 + (i * 7) % 200));
    }
    return {
      grid: { left: 56, right: 16, top: 40, bottom: 32 },
      legend: { data: ['训练', '推理', '开发机'], right: 0 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: days, boundaryGap: false },
      yAxis: {
        type: 'value',
        name: '¥',
        splitLine: { lineStyle: { type: 'dashed' } },
      },
      series: [
        {
          name: '训练',
          type: 'line',
          stack: 'cost',
          areaStyle: { color: 'rgba(22,119,255,0.35)' },
          lineStyle: { color: token.colorPrimary },
          itemStyle: { color: token.colorPrimary },
          smooth: true,
          data: training,
        },
        {
          name: '推理',
          type: 'line',
          stack: 'cost',
          areaStyle: { color: 'rgba(82,196,26,0.35)' },
          lineStyle: { color: token.colorSuccess },
          itemStyle: { color: token.colorSuccess },
          smooth: true,
          data: inference,
        },
        {
          name: '开发机',
          type: 'line',
          stack: 'cost',
          areaStyle: { color: 'rgba(250,173,20,0.35)' },
          lineStyle: { color: token.colorWarning },
          itemStyle: { color: token.colorWarning },
          smooth: true,
          data: dev,
        },
      ],
    };
  }, [token]);

  /** Cluster node state distribution. */
  const nodeHealthOption = useMemo<EChartsOption>(
    () => ({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 10 },
      series: [
        {
          type: 'pie',
          radius: ['50%', '75%'],
          avoidLabelOverlap: false,
          label: { show: false },
          data: [
            { value: 84, name: 'Ready', itemStyle: { color: token.colorSuccess } },
            {
              value: 2,
              name: 'NotReady',
              itemStyle: { color: token.colorError },
            },
            {
              value: 1,
              name: 'SchedulingDisabled',
              itemStyle: { color: token.colorWarning },
            },
          ],
        },
      ],
    }),
    [token],
  );

  const gpuUtil = 74;
  const activeWs = 6;
  const totalWs = mockWorkspaces.length;
  const activeUsers = 23;
  const totalUsers = 128;
  const costMtd = 142_380;
  const budget = 160_000;

  return (
    <PageContainer
      title="全局仪表盘"
      subTitle="全集群资源、告警与成本总览"
      extra={[
        <Select
          key="range"
          value={timeRange}
          onChange={(v) => setTimeRange(v)}
          style={{ width: 120 }}
          options={[
            { value: 'today', label: '今日' },
            { value: 'week', label: '本周' },
            { value: 'month', label: '本月' },
          ]}
        />,
      ]}
    >
      {/* KPI row */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card
            style={{
              borderLeft: `4px solid ${token.colorPrimary}`,
              borderRadius: 12,
            }}
          >
            <Statistic
              title="集群 GPU 利用率"
              value={gpuUtil}
              suffix="%"
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: token.colorPrimary, fontWeight: 600 }}
            />
            <Space style={{ marginTop: 8 }}>
              <ArrowUpOutlined style={{ color: token.colorSuccess }} />
              <Text style={{ fontSize: 12 }} type="secondary">
                昨日 +12% · 近 7 天峰值 91%
              </Text>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card
            style={{
              borderLeft: `4px solid ${token.colorWarning}`,
              borderRadius: 12,
            }}
          >
            <Statistic
              title="活跃工作空间"
              value={activeWs}
              suffix={`/ ${totalWs}`}
              prefix={<CloudServerOutlined />}
              valueStyle={{ color: token.colorWarning, fontWeight: 600 }}
            />
            <Text style={{ fontSize: 12 }} type="secondary">
              {totalWs - activeWs} 个近 7 天无活动
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card
            style={{
              borderLeft: `4px solid ${token.colorSuccess}`,
              borderRadius: 12,
            }}
          >
            <Statistic
              title="在线用户"
              value={activeUsers}
              suffix={`/ ${totalUsers}`}
              prefix={<TeamOutlined />}
              valueStyle={{ color: token.colorSuccess, fontWeight: 600 }}
            />
            <Text style={{ fontSize: 12 }} type="secondary">
              今日登录 / 总成员
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card
            style={{
              borderLeft: `4px solid ${token.colorError}`,
              borderRadius: 12,
            }}
          >
            <Statistic
              title="月消耗"
              value={costMtd}
              prefix={<DollarOutlined />}
              formatter={(v) => `¥${Number(v).toLocaleString()}`}
              valueStyle={{ color: token.colorError, fontWeight: 600 }}
            />
            <Progress
              percent={Math.round((costMtd / budget) * 100)}
              size="small"
              strokeColor={token.colorError}
              showInfo={false}
              style={{ marginTop: 4 }}
            />
            <Text style={{ fontSize: 12 }} type="secondary">
              预算 ¥{budget.toLocaleString()} · 剩余 ¥
              {(budget - costMtd).toLocaleString()}
            </Text>
          </Card>
        </Col>
      </Row>

      {/* Middle: ranking + alerts */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={16}>
          <Card
            title="Top 工作空间资源占用排行"
            extra={<Button type="link">查看全部 →</Button>}
            style={{ borderRadius: 12 }}
          >
            <ReactECharts
              option={rankingOption}
              style={{ height: 320 }}
              notMerge
            />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card
            title={
              <Space>
                <AlertOutlined />
                实时告警流
              </Space>
            }
            extra={<Text type="secondary">{ADMIN_ALERTS.length} 条</Text>}
            style={{ borderRadius: 12 }}
          >
            <List
              dataSource={ADMIN_ALERTS}
              renderItem={(item) => {
                const cfg: Record<
                  AlertLevel,
                  { color: string; tag: string; tagColor: string }
                > = {
                  error: {
                    color: token.colorError,
                    tag: 'CRITICAL',
                    tagColor: 'error',
                  },
                  warning: {
                    color: token.colorWarning,
                    tag: 'WARN',
                    tagColor: 'warning',
                  },
                  info: { color: '#999', tag: 'INFO', tagColor: 'default' },
                };
                const c = cfg[item.level];
                return (
                  <List.Item style={{ padding: '10px 0' }}>
                    <Space
                      direction="vertical"
                      size={2}
                      style={{ width: '100%' }}
                    >
                      <Space size={6}>
                        <Tag color={c.tagColor} style={{ margin: 0 }}>
                          {c.tag}
                        </Tag>
                        <Text style={{ fontSize: 12 }} type="secondary">
                          {dayjs(item.ts).fromNow()} · {item.source}
                        </Text>
                      </Space>
                      <Text style={{ fontSize: 13, color: c.color }}>
                        {item.message}
                      </Text>
                    </Space>
                  </List.Item>
                );
              }}
            />
          </Card>
        </Col>
      </Row>

      {/* Bottom: cluster health + cost trend */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={10}>
          <Card title="集群健康度" style={{ borderRadius: 12, height: '100%' }}>
            <Row gutter={16}>
              <Col xs={24} sm={10}>
                <ReactECharts
                  option={nodeHealthOption}
                  style={{ height: 220 }}
                  notMerge
                />
                <div style={{ textAlign: 'center', marginTop: -8 }}>
                  <Text strong>节点总计 87</Text>
                </div>
              </Col>
              <Col xs={24} sm={14}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  故障节点 ({FAILED_NODES.length})
                </Text>
                <List
                  size="small"
                  dataSource={FAILED_NODES}
                  renderItem={(n) => (
                    <List.Item style={{ paddingInline: 0 }}>
                      <Space direction="vertical" size={0}>
                        <Space size={6}>
                          <WarningOutlined style={{ color: token.colorError }} />
                          <Text strong style={{ fontSize: 12 }}>
                            {n.id}
                          </Text>
                        </Space>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {n.reason} · {n.zone} ·{' '}
                          {dayjs(n.since).fromNow()}
                        </Text>
                      </Space>
                    </List.Item>
                  )}
                />
                <div style={{ marginTop: 12 }}>
                  <Badge
                    status="success"
                    text={<Text style={{ fontSize: 12 }}>4 个 Operator 全部 OK</Text>}
                  />
                  <div style={{ marginTop: 4 }}>
                    <Space size={6} wrap>
                      <Tag icon={<CheckCircleOutlined />} color="success">
                        workspace-controller
                      </Tag>
                      <Tag icon={<CheckCircleOutlined />} color="success">
                        observability-webhook
                      </Tag>
                      <Tag icon={<CheckCircleOutlined />} color="success">
                        platform-api 3/3
                      </Tag>
                      <Tag icon={<CheckCircleOutlined />} color="success">
                        training-operator
                      </Tag>
                    </Space>
                  </div>
                </div>
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} xl={14}>
          <Card
            title="成本趋势 (近 30 天)"
            extra={
              <Space size={16}>
                <Text type="secondary">
                  <ExclamationCircleOutlined /> 数据截至{' '}
                  {dayjs().subtract(1, 'day').format('MM-DD')}
                </Text>
              </Space>
            }
            style={{ borderRadius: 12, height: '100%' }}
          >
            <ReactECharts
              option={costTrendOption}
              style={{ height: 300 }}
              notMerge
            />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
