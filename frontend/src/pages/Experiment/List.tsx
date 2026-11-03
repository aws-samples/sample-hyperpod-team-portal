import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Card,
  Col,
  Row,
  Space,
  Tag,
  Tree,
  message,
} from 'antd';
import type { TreeDataNode } from 'antd';
import {
  ExperimentOutlined,
  ExportOutlined,
  PlusOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import dayjs from 'dayjs';
import { useAppStore } from '@/store';
import { SEMANTIC_COLORS, withAlpha } from '@/shared/ui/metrics/chartTheme';
import { mockTrainingJobs } from '@/mock/trainingJobs';
import { mockWorkspaces } from '@/mock/workspaces';

/**
 * Interpolate between two hex colors — used to paint each parallel line a
 * shade that reflects its final_loss value (low=green, high=red). Cheap and
 * deterministic; avoids pulling in chroma-js just for this one thing.
 */
const lerpHex = (a: string, b: string, t: number): string => {
  const pa = a.replace('#', '');
  const pb = b.replace('#', '');
  const ar = parseInt(pa.slice(0, 2), 16);
  const ag = parseInt(pa.slice(2, 4), 16);
  const ab = parseInt(pa.slice(4, 6), 16);
  const br = parseInt(pb.slice(0, 2), 16);
  const bg = parseInt(pb.slice(2, 4), 16);
  const bb = parseInt(pb.slice(4, 6), 16);
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  return `rgb(${clamp(ar + (br - ar) * t)}, ${clamp(ag + (bg - ag) * t)}, ${clamp(
    ab + (bb - ab) * t,
  )})`;
};

interface Run {
  id: string;
  experimentId: string;
  name: string;
  status: 'running' | 'done' | 'failed' | 'killed';
  startedAt: string;
  durationMin: number;
  params: {
    learning_rate: number;
    batch_size: number;
    epochs: number;
    warmup_steps: number;
    optimizer: string;
  };
  metrics: {
    final_loss: number;
    accuracy: number;
  };
}

interface Experiment {
  id: string;
  name: string;
  description: string;
  runCount: number;
  owner: string;
  createdAt: string;
  tags: string[];
}

// Build deterministic experiment + run dataset from existing training mock data.
const buildExperiments = (): { exps: Experiment[]; runs: Run[] } => {
  const exps: Experiment[] = [
    {
      id: 'exp-001',
      name: 'llama3-sft-april',
      description: 'Llama-3 70B SFT hyperparam sweep',
      runCount: 5,
      owner: 'alice@example.com',
      createdAt: '2026-04-01T10:00:00Z',
      tags: ['llama3', 'sft', '70b'],
    },
    {
      id: 'exp-002',
      name: 'qwen2-rlhf-april',
      description: 'Qwen2 72B RLHF preference tuning',
      runCount: 3,
      owner: 'bob@example.com',
      createdAt: '2026-04-05T10:00:00Z',
      tags: ['qwen2', 'rlhf'],
    },
    {
      id: 'exp-003',
      name: 'baseline-benchmark',
      description: 'Model quality baseline',
      runCount: 4,
      owner: 'carol@example.com',
      createdAt: '2026-03-20T10:00:00Z',
      tags: ['benchmark'],
    },
  ];

  const runs: Run[] = [];
  const lrs = [1e-5, 2e-5, 5e-5, 1e-4];
  const bss = [16, 32, 64, 128];
  const epochsOpts = [2, 3, 4];
  const warmups = [200, 500, 1000];
  const optims = ['adamw', 'sgd', 'adafactor'];

  exps.forEach((exp) => {
    for (let i = 0; i < exp.runCount; i += 1) {
      const seed = i * 7 + exp.id.length;
      const status: Run['status'] =
        i === 0 && exp.id === 'exp-001'
          ? 'running'
          : i === exp.runCount - 1 && exp.id === 'exp-002'
          ? 'failed'
          : 'done';
      const lr = lrs[seed % lrs.length];
      const bs = bss[(seed * 3) % bss.length];
      const final_loss = status === 'failed' ? 4.2 : 1.6 + (seed % 6) * 0.08;
      runs.push({
        id: `${exp.id}-run-${i + 1}`,
        experimentId: exp.id,
        name: `run-${dayjs().subtract(i * 6, 'hour').format('MMDD-HHmm')}`,
        status,
        startedAt: dayjs().subtract(i * 6, 'hour').toISOString(),
        durationMin: 120 + (seed * 17) % 200,
        params: {
          learning_rate: lr,
          batch_size: bs,
          epochs: epochsOpts[seed % epochsOpts.length],
          warmup_steps: warmups[seed % warmups.length],
          optimizer: optims[seed % optims.length],
        },
        metrics: {
          final_loss: Number(final_loss.toFixed(3)),
          accuracy: status === 'failed' ? 0 : Number((0.78 + (seed % 8) * 0.01).toFixed(3)),
        },
      });
    }
  });

  return { exps, runs };
};

export default function ExperimentList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const workspaceName = useMemo(
    () => mockWorkspaces.find((w) => w.id === wsId)?.displayName ?? '工作空间',
    [wsId],
  );
  const { exps, runs } = useMemo(buildExperiments, []);
  const [selectedExpId, setSelectedExpId] = useState<string>(exps[0].id);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);

  const selectedExp = exps.find((e) => e.id === selectedExpId);
  const expRuns = useMemo(
    () => runs.filter((r) => r.experimentId === selectedExpId),
    [runs, selectedExpId],
  );

  // Best run (lowest final_loss among done runs)
  const bestRunId = useMemo(() => {
    const done = expRuns.filter((r) => r.status === 'done');
    if (done.length === 0) return null;
    return done.reduce((min, r) =>
      r.metrics.final_loss < min.metrics.final_loss ? r : min,
    ).id;
  }, [expRuns]);

  const treeData: TreeDataNode[] = useMemo(
    () =>
      exps.map((e) => {
        const eRuns = runs.filter((r) => r.experimentId === e.id);
        return {
          title: (
            <Space size={6}>
              <span style={{ fontWeight: 500 }}>{e.name}</span>
              <Badge
                count={eRuns.length}
                style={{ backgroundColor: '#1677ff' }}
              />
            </Space>
          ),
          key: e.id,
          icon: <ExperimentOutlined />,
          selectable: true,
          children: eRuns.map((r) => ({
            title: (
              <span style={{ fontSize: 12, color: '#595959' }}>{r.name}</span>
            ),
            key: r.id,
            isLeaf: true,
            selectable: false,
          })),
        };
      }),
    [exps, runs],
  );

  const themeMode = useAppStore((s) => s.themeMode);

  // Parallel coordinates option — each line is colored by its final_loss on a
  // green→amber→red scale so the screenshot tells a story at a glance:
  // good runs look calm and green, overfit/unstable runs jump out red.
  const parallelOption = useMemo<EChartsOption>(() => {
    const comparedRuns = expRuns.filter((r) => r.status !== 'failed');
    const losses = comparedRuns.map((r) => r.metrics.final_loss);
    const minLoss = Math.min(...losses, 0);
    const maxLoss = Math.max(...losses, 1);
    const lossNorm = (v: number) =>
      maxLoss === minLoss ? 0 : (v - minLoss) / (maxLoss - minLoss);

    const goodColor = SEMANTIC_COLORS.throughput; // green
    const midColor = SEMANTIC_COLORS.itl; // orange
    const badColor = SEMANTIC_COLORS.errors; // deep red

    const colorForLoss = (t: number): string =>
      t < 0.5 ? lerpHex(goodColor, midColor, t * 2) : lerpHex(midColor, badColor, (t - 0.5) * 2);

    const isDark = themeMode === 'dark';
    const axisTextColor = isDark
      ? 'rgba(255,255,255,0.75)'
      : 'rgba(0,0,0,0.75)';
    const axisLineColor = isDark ? '#2a3040' : '#d9d9d9';
    const tooltipBg = isDark
      ? 'rgba(20, 20, 30, 0.92)'
      : 'rgba(255, 255, 255, 0.98)';
    const tooltipText = isDark ? 'rgba(255,255,255,0.92)' : '#1f1f1f';
    const tooltipBorder = isDark
      ? 'rgba(255,255,255,0.12)'
      : '#e5e7eb';

    return {
      backgroundColor: 'transparent',
      parallelAxis: [
        {
          dim: 0,
          name: 'learning_rate',
          type: 'log',
          logBase: 10,
          axisLabel: {
            formatter: (v: number) => `${v.toExponential(0)}`,
            fontSize: 11,
            color: axisTextColor,
          },
        },
        {
          dim: 1,
          name: 'batch_size',
          axisLabel: { fontSize: 11, color: axisTextColor },
        },
        {
          dim: 2,
          name: 'epochs',
          axisLabel: { fontSize: 11, color: axisTextColor },
        },
        {
          dim: 3,
          name: 'final_loss',
          inverse: true,
          axisLabel: { fontSize: 11, color: axisTextColor },
        },
        {
          dim: 4,
          name: 'accuracy',
          axisLabel: {
            formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
            fontSize: 11,
            color: axisTextColor,
          },
        },
      ],
      parallel: {
        left: '5%',
        right: '13%',
        bottom: '12%',
        top: '18%',
        parallelAxisDefault: {
          axisLine: { lineStyle: { color: axisLineColor, width: 1 } },
          axisTick: { lineStyle: { color: axisLineColor } },
          axisLabel: { fontSize: 11, color: axisTextColor },
          nameTextStyle: {
            fontSize: 12,
            fontWeight: 600,
            color: axisTextColor,
          },
          splitLine: { show: false },
        },
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        borderWidth: 1,
        extraCssText: 'box-shadow:0 6px 24px -4px rgba(15,23,42,0.18);border-radius:8px;backdrop-filter:blur(8px);',
        textStyle: { color: tooltipText, fontSize: 12 },
        formatter: (params) => {
          const p = params as unknown as {
            data: [number, number, number, number, number];
            name: string;
          };
          const rows = [
            ['lr', p.data[0].toExponential(1)],
            ['batch_size', String(p.data[1])],
            ['epochs', String(p.data[2])],
            ['final_loss', p.data[3].toFixed(3)],
            ['accuracy', `${(p.data[4] * 100).toFixed(1)}%`],
          ];
          return `
            <div style="min-width:180px;">
              <div style="color:${tooltipText};font-weight:600;margin-bottom:6px;">${p.name}</div>
              ${rows
                .map(
                  ([k, v]) =>
                    `<div style="display:flex;justify-content:space-between;gap:16px;line-height:20px;">
                       <span style="color:${tooltipText};opacity:0.7;">${k}</span>
                       <span style="color:${tooltipText};font-weight:600;font-variant-numeric:tabular-nums;">${v}</span>
                     </div>`,
                )
                .join('')}
            </div>`;
        },
      },
      series: [
        {
          name: 'runs',
          type: 'parallel',
          lineStyle: { width: 2, opacity: 0.75 },
          emphasis: {
            focus: 'series',
            lineStyle: { width: 4, opacity: 1 },
          },
          // Fade other lines when one is hovered — classic parallel-coords UX.
          blendMode: 'source-over',
          inactiveOpacity: 0.08,
          activeOpacity: 1,
          data: comparedRuns.map((r) => {
            const color = colorForLoss(lossNorm(r.metrics.final_loss));
            return {
              name: r.name,
              value: [
                r.params.learning_rate,
                r.params.batch_size,
                r.params.epochs,
                r.metrics.final_loss,
                r.metrics.accuracy,
              ],
              lineStyle: {
                color,
                width: 2,
                shadowColor: withAlpha(color, 0.35),
                shadowBlur: 4,
              },
            };
          }),
        },
      ],
    };
  }, [expRuns, themeMode]);

  const columns: ProColumns<Run>[] = [
    {
      title: 'Run 名称',
      dataIndex: 'name',
      width: 180,
      render: (_, row) => (
        <Space>
          <span>{row.name}</span>
          {row.id === bestRunId && <Tag color="gold">★ Best</Tag>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueEnum: {
        running: { text: '运行中', status: 'Processing' },
        done: { text: '已完成', status: 'Success' },
        failed: { text: '已失败', status: 'Error' },
        killed: { text: '已终止', status: 'Warning' },
      },
    },
    {
      title: '超参摘要',
      width: 280,
      search: false,
      render: (_, r) => (
        <Space size={4} wrap>
          <Tag color="blue">lr={r.params.learning_rate.toExponential(1)}</Tag>
          <Tag color="cyan">bs={r.params.batch_size}</Tag>
          <Tag>epochs={r.params.epochs}</Tag>
          <Tag>{r.params.optimizer}</Tag>
        </Space>
      ),
    },
    {
      title: '最终 loss',
      dataIndex: ['metrics', 'final_loss'],
      width: 110,
      search: false,
      render: (_, r) =>
        r.status === 'failed' ? (
          <Tag color="red">NaN</Tag>
        ) : (
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>
            {r.metrics.final_loss.toFixed(3)}
          </span>
        ),
    },
    {
      title: '最高 accuracy',
      dataIndex: ['metrics', 'accuracy'],
      width: 120,
      search: false,
      render: (_, r) =>
        r.status === 'failed' ? '-' : (r.metrics.accuracy * 100).toFixed(1) + '%',
    },
    {
      title: '训练时长',
      dataIndex: 'durationMin',
      width: 110,
      search: false,
      render: (_, r) => {
        const h = Math.floor(r.durationMin / 60);
        const m = r.durationMin % 60;
        return h > 0 ? `${h}h ${m}m` : `${m}m`;
      },
    },
    {
      title: '开始时间',
      dataIndex: 'startedAt',
      width: 150,
      search: false,
      render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 130,
      search: false,
      render: (_, r) => {
        // Link to the training job (mock: fallback to first job if none match).
        const jobId = mockTrainingJobs[0]?.id ?? '';
        return (
          <Space>
            <a
              onClick={() => {
                if (jobId) {
                  window.location.hash = `/workspaces/${wsId}/training/${jobId}`;
                }
              }}
            >
              详情
            </a>
            <a>克隆</a>
            <span style={{ color: '#bfbfbf' }}>({r.id.slice(-3)})</span>
          </Space>
        );
      },
    },
  ];

  return (
    <PageContainer
      header={{
        title: '实验管理',
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{workspaceName}</a> },
            { title: '实验管理' },
          ],
        },
      }}
      extra={[
        <Button
          key="compare"
          icon={<SwapOutlined />}
          disabled={selectedRunIds.length < 2}
          onClick={() =>
            message.info(`对比 ${selectedRunIds.length} 个 Run（UI 已就绪）`)
          }
        >
          对比选中 Run ({selectedRunIds.length})
        </Button>,
        <Button key="export" icon={<ExportOutlined />}>
          导出 CSV
        </Button>,
        <Button key="new" type="primary" icon={<PlusOutlined />}>
          新建实验
        </Button>,
      ]}
    >
      <Row gutter={16}>
        <Col xs={24} lg={6}>
          <Card size="small" title="实验树" bordered={false}>
            <Tree
              treeData={treeData}
              defaultExpandAll
              showIcon
              selectedKeys={[selectedExpId]}
              onSelect={(keys) => {
                if (keys.length > 0 && exps.find((e) => e.id === keys[0])) {
                  setSelectedExpId(String(keys[0]));
                  setSelectedRunIds([]);
                }
              }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={18}>
          <Card
            size="small"
            title={
              <Space>
                <ExperimentOutlined />
                <span>{selectedExp?.name}</span>
                {selectedExp?.tags.map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </Space>
            }
            extra={
              <span style={{ color: '#8c8c8c', fontSize: 12 }}>
                {selectedExp?.description} · Owner: {selectedExp?.owner}
              </span>
            }
            bordered={false}
            style={{ marginBottom: 16 }}
          >
            <ProTable<Run>
              rowKey="id"
              columns={columns}
              dataSource={expRuns}
              search={false}
              pagination={false}
              toolBarRender={false}
              options={false}
              rowSelection={{
                selectedRowKeys: selectedRunIds,
                onChange: (keys) => setSelectedRunIds(keys as string[]),
              }}
              scroll={{ x: 1100 }}
            />
          </Card>

          <Card
            size="small"
            title="超参 × 指标 · Parallel Coordinates"
            bordered={false}
            extra={
              <span style={{ color: '#8c8c8c', fontSize: 12 }}>
                拖动坐标轴重排 · 轴上圈选可过滤
              </span>
            }
          >
            <ReactECharts
              option={parallelOption}
              style={{ height: 360 }}
              notMerge
              lazyUpdate
            />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
