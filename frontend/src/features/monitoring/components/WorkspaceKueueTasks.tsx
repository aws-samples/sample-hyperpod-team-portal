/**
 * WorkspaceKueueTasks · 队列/配额监控页表格的「展开行」内容。
 *
 * 点某工作空间的「排队中的Pod（Inadmissible）」计数后, 该行向下展开渲染本组件: 列出该 ws
 * 「排队中」(Kueue 状态 = Queued) 的任务 + 排队顺序 + 各自实时 Kueue 状态。与「任务总览」的
 * 排队中视图一致:
 *   - 「排队顺序」列 = Kueue LocalQueue 真实身位 (getTaskQueueOrder);
 *   - 多调度单元 (Workload) 的任务可展开「+」(默认展开) 看每个单元的排队明细;
 *   - 点「Kueue 详情」经 onShowDetail 上抛给页面, 由页面级面板从右侧挤出显示 conditions。
 *
 * 数据源: GET /workspaces/{id}/tasks (getTaskOverview) + /tasks/queue-order (getTaskQueueOrder)。
 *
 * ⚠️ 无法准入无法在前端精确挑出: 表头 inadmissible 计数来自 Prometheus 指标 (仅队列级数量、无
 * workload 身份); kueue_status 只到六态 (Queued 既含正常排队也含无法准入)。故列「排队中」全部任务,
 * 是否无法准入 / 原因点「Kueue 详情」看 conditions。
 *
 * Kueue 详情端点按类型 by-id 取: 训练 / 开发机 / 单机推理 支持; 多机推理 (llmd) 需 workload 名、
 * Dynamo 无该端点 —— 这两类的「Kueue 详情」置灰。
 *
 * 权限: 端点仅 ws 管理员 / 平台超管可访问, 非管理员 403 (面板内友好提示)。
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Badge, Space, Spin, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { Key } from 'react';
import ColTitle from '@/shared/ui/ColTitle';
import { ApiError } from '@/shared/api';
import { kueueStatusColor, kueueStatusLabel } from '@/shared/status';
import type { KueueDetail } from '@/shared/kueue';
import { getTaskOverview, getTaskQueueOrder } from '@/features/tasks/api';
import type { QueueEntry, QueueWorkload, TaskKind, TaskRow } from '@/features/tasks/api';
import { getTrainingKueueDetail } from '@/features/training/api/client';
import { getDevInstanceKueueDetail } from '@/features/devinstance/api/client';
import { getInferenceKueueDetail } from '@/features/inference/api/client';

const { Text } = Typography;

// label 存 key, 渲染时再 t()。
const KIND_META = {
  dev: { labelKey: 'kueueTasks.kind.dev', color: 'blue' },
  train: { labelKey: 'kueueTasks.kind.train', color: 'purple' },
  inference: { labelKey: 'kueueTasks.kind.inference', color: 'cyan' },
  dynamo: { labelKey: 'kueueTasks.kind.dynamo', color: 'geekblue' },
  llmd: { labelKey: 'kueueTasks.kind.llmd', color: 'magenta' },
  rayjob: { labelKey: 'kueueTasks.kind.rayjob', color: 'gold' },
} as const satisfies Record<TaskKind, { labelKey: string; color: string }>;

/**
 * 按类型返回 by-id 的 Kueue 详情取数函数; llmd/dynamo 无 by-id 端点 → null (详情置灰)。
 * 页面级详情面板也复用此函数为选中任务构造 fetcher。
 */
export function kueueDetailFetcher(task: TaskRow): (() => Promise<KueueDetail>) | null {
  switch (task.kind) {
    case 'train':
      return () => getTrainingKueueDetail(task.id);
    case 'dev':
      return () => getDevInstanceKueueDetail(task.id);
    case 'inference':
      return () => getInferenceKueueDetail(task.id);
    default:
      return null;
  }
}

interface Props {
  workspaceId: string;
  /** 表头该 ws 的 inadmissible 计数 — 仅用于面板顶部提示 (指标来源, 无身份)。 */
  inadmissibleCount: number;
  /** 点「Kueue 详情」上抛给页面, 由页面级面板从右侧挤出。 */
  onShowDetail: (task: TaskRow) => void;
}

export default function WorkspaceKueueTasks({
  workspaceId,
  inadmissibleCount,
  onShowDetail,
}: Props) {
  const { t } = useTranslation(['monitoring', 'common']);
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<TaskRow[]>([]);
  // Kueue LocalQueue 真实排队顺序 {cr_name: {position(min), workloads:[...]}}。
  const [queueOrder, setQueueOrder] = useState<Record<string, QueueEntry>>({});
  // 默认展开有多调度单元的任务, 直接摊开排队明细。
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    if (!workspaceId) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setForbidden(false);
    Promise.all([
      getTaskOverview(workspaceId),
      // 排队顺序查不到不阻塞主列表 (静默降级为空 → 身位显 "-")。
      getTaskQueueOrder(workspaceId).catch(
        () => ({}) as Record<string, QueueEntry>,
      ),
    ])
      .then(([overview, order]) => {
        if (cancelled) return;
        const queued = overview.tasks.filter((task) => task.kueue_status === 'Queued');
        const posOf = (r: TaskRow) => {
          const e = r.k8s_name != null ? order[r.k8s_name] : undefined;
          return e != null ? e.position : Number.MAX_SAFE_INTEGER;
        };
        // 按 Kueue 真实身位升序 (无身位垫底), 与任务总览「排队中」一致。
        const sorted = [...queued].sort((a, b) => posOf(a) - posOf(b));
        setRows(sorted);
        setQueueOrder(order);
        setExpandedKeys(
          sorted
            .filter((r) => {
              // 多机推理 (llmd) 默认不展开: Workload 多, 收起更清爽 (仍可手动点「+」)。
              if (r.kind === 'llmd') return false;
              const e = r.k8s_name != null ? order[r.k8s_name] : undefined;
              return e != null && e.workloads.length > 1;
            })
            .map((r) => r.id),
        );
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        else setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  // 每个调度单元 (Workload) 的排队明细子表 —— 与任务总览一致。
  const subColumns: ColumnsType<QueueWorkload> = [
    {
      title: 'Workload',
      dataIndex: 'name',
      key: 'name',
      width: 260,
      ellipsis: { showTitle: true },
    },
    {
      title: t('kueueTasks.columns.queueOrder'),
      dataIndex: 'position',
      key: 'position',
      width: 130,
      render: (p: number) => p + 1,
    },
    { title: t('kueueTasks.columns.priority'), dataIndex: 'priority', key: 'priority', width: 90 },
  ];

  const columns: ColumnsType<TaskRow> = [
    {
      title: t('kueueTasks.columns.type'),
      dataIndex: 'kind',
      width: 180, // en: "Single-node Inference" 比中文长
      render: (_, row) => {
        const meta = Object.hasOwn(KIND_META, row.kind) ? KIND_META[row.kind] : undefined;
        return <Tag color={meta?.color}>{meta ? t(meta.labelKey) : row.kind}</Tag>;
      },
    },
    {
      title: t('kueueTasks.columns.taskName'),
      dataIndex: 'name',
      ellipsis: true,
      render: (_, row) => (
        <Tooltip title={row.name ?? row.id}>
          <Text>{row.name ?? row.id}</Text>
        </Tooltip>
      ),
    },
    {
      title: (
        <ColTitle
          text={t('kueueTasks.columns.queueOrder')}
          tip={t('kueueTasks.columns.queueOrderTip')}
        />
      ),
      key: 'queueOrder',
      width: 160,
      render: (_, row) => {
        const e = row.k8s_name != null ? queueOrder[row.k8s_name] : undefined;
        if (e == null) return <Text type="secondary">-</Text>;
        return <span>{e.position + 1}</span>;
      },
    },
    {
      title: t('kueueTasks.columns.kueueStatus'),
      dataIndex: 'kueue_status',
      width: 200,
      render: (_, row) => {
        const label = kueueStatusLabel(row.kueue_status);
        const badge = label ? (
          <Badge status={kueueStatusColor(row.kueue_status)} text={label} />
        ) : (
          <Text type="secondary">-</Text>
        );
        const canInspect = kueueDetailFetcher(row) !== null;
        return (
          <Space size={8}>
            {badge}
            {canInspect ? (
              <a onClick={() => onShowDetail(row)}>{t('common:kueueStatus.detailLink')}</a>
            ) : (
              <Tooltip title={t('kueueTasks.detailUnsupported')}>
                <Text type="secondary" style={{ fontSize: 12, cursor: 'not-allowed' }}>
                  {t('common:kueueStatus.detailLink')}
                </Text>
              </Tooltip>
            )}
          </Space>
        );
      },
    },
  ];

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '16px 0' }}>
        <Spin size="small" />
      </div>
    );
  }
  if (forbidden) {
    return (
      <Alert
        type="warning"
        showIcon
        banner
        message={t('kueueTasks.forbidden.title')}
        description={t('kueueTasks.forbidden.description')}
      />
    );
  }
  if (err) {
    return <Alert type="error" showIcon banner message={t('kueueTasks.loadFailed')} description={err} />;
  }
  if (rows.length === 0) {
    return (
      <Alert
        type="success"
        showIcon
        banner
        message={t('kueueTasks.empty.title')}
        description={t('kueueTasks.empty.description')}
      />
    );
  }

  return (
    <>
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
        {t('kueueTasks.intro', { inadmissible: inadmissibleCount })}
      </Text>
      <Table<TaskRow>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        size="small"
        pagination={{ defaultPageSize: 10, hideOnSinglePage: true }}
        expandable={{
          // 多调度单元 (Workload) 的任务才可展开; 默认展开 (expandedKeys 已预置)。
          rowExpandable: (row) => {
            const e = row.k8s_name != null ? queueOrder[row.k8s_name] : undefined;
            return e != null && e.workloads.length > 1;
          },
          expandedRowKeys: expandedKeys,
          onExpandedRowsChange: (keys) => setExpandedKeys([...keys]),
          expandedRowRender: (row) => {
            const e = row.k8s_name != null ? queueOrder[row.k8s_name] : undefined;
            return (
              <Table<QueueWorkload>
                size="small"
                rowKey={(w) => w.name || String(w.position)}
                columns={subColumns}
                dataSource={e?.workloads ?? []}
                pagination={false}
              />
            );
          },
        }}
      />
    </>
  );
}
