import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { Alert, App, Badge, Button, Input, Result, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DownOutlined,
  EditOutlined,
  FilterOutlined,
  ReloadOutlined,
  UpOutlined,
} from '@ant-design/icons';
import ColTitle from '@/shared/ui/ColTitle';
import dayjs from 'dayjs';
import { ApiError } from '@/shared/api';
import { phaseColor } from '@/shared/status';
import { barePhase } from '@/features/rayjob/api/types';
import { getTaskOverview, getTaskQueueOrder } from '../api';
import type { QueueEntry, QueueWorkload, TaskKind, TaskRow } from '../api';
import ChangePriorityModal from '../components/ChangePriorityModal';
import FilterBar from '@/shared/ui/FilterBar';
import PageDescription from '@/shared/ui/PageDescription';
import { HIDDEN_FEATURE_SEGMENTS } from '@/config/features';

// label 存 key, 渲染时再 t() (语言切换走整页刷新)。
const KIND_META = {
  dev: { labelKey: 'overview.kind.dev', color: 'blue', route: 'dev' },
  train: { labelKey: 'overview.kind.train', color: 'purple', route: 'training' },
  inference: { labelKey: 'overview.kind.inference', color: 'cyan', route: 'inference' },
  dynamo: { labelKey: 'overview.kind.dynamo', color: 'geekblue', route: 'dynamo' },
  llmd: { labelKey: 'overview.kind.llmd', color: 'magenta', route: 'llmd' },
  rayjob: { labelKey: 'overview.kind.rayjob', color: 'orange', route: 'rayjob' },
} as const satisfies Record<TaskKind, { labelKey: string; color: string; route: string }>;


export default function TasksOverview() {
  const { wsId = '' } = useParams();
  const { t } = useTranslation(['tasks', 'common']);
  const { message } = App.useApp();
  const [rows, setRows] = useState<TaskRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [kindTab, setKindTab] = useState<'all' | TaskKind>('all');
  // 活跃范围切换 (纯前端过滤, 后端恒返全部活跃):
  //   'all'=全部 / 'queued'=排队中(ks===Queued) / 'running'=运行中(ks!==Queued)。
  //   排队中 + 运行中 = 全部 (互斥完备)。默认排队中 (最贴合调优先级场景)。
  const [queueScope, setQueueScope] = useState<'all' | 'queued' | 'running'>('queued');
  // Kueue LocalQueue 真实排队顺序 {cr_name: 0-based position}; 仅"只看排队"范围拉取。
  const [queueOrder, setQueueOrder] = useState<Record<string, QueueEntry>>({});
  // 名称搜索 (纯前端过滤, 不打后端)。
  const [nameFilter, setNameFilter] = useState('');
  // 当前用户是否可改本 ws 任务优先级 (后端算: 超管 OR ws admin)。
  const [canEdit, setCanEdit] = useState(false);
  // 正在改优先级的任务 (null = Modal 关闭)。
  const [editingTask, setEditingTask] = useState<TaskRow | null>(null);
  // 后端返 403 = 非 ws 管理员 / 超管 (任务总览仅管理员可见)。显示无权限态而非空表。
  const [forbidden, setForbidden] = useState(false);
  // 两个 tip 合并到一行: 点 chip 切换 activeTip; 同一 chip 再点一次收起。
  const [activeTip, setActiveTip] = useState<'rules' | 'status' | null>(null);
  // 列头筛选漏斗默认隐藏, 点「筛选」按钮才显 (状态/排队状态/优先级档位/创建者四列)
  const [filterEnabled, setFilterEnabled] = useState(false);

  const reload = () => {
    if (!wsId) return;
    setLoading(true);
    setForbidden(false);
    getTaskOverview(wsId)
      .then((res) => {
        setRows(res.tasks);
        setCanEdit(res.can_edit_priority);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 403) {
          setForbidden(true);
        } else {
          message.error(t('overview.loadFailed', { error: String(e) }));
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  // 拉 Kueue 排队顺序 (所有范围都拉; 排队顺序列始终显示, 非排队任务不在 map → 显 -)。查失败后端返 {}。
  const reloadQueueOrder = useCallback(() => {
    getTaskQueueOrder(wsId)
      .then(setQueueOrder)
      .catch(() => setQueueOrder({}));
  }, [wsId]);

  useEffect(() => {
    reloadQueueOrder();
  }, [reloadQueueOrder]);

  // scope 过滤: 应用 queueScope (全部/排队中/运行中) + 名称搜索, 但不含类型 tab。
  // tab 计数与表格数据都基于它, 保证切 queueScope/搜索时 tab 数字同步变 (kindTab 是
  // tab 自身的过滤, 不参与计数 base)。
  const scopeFiltered = useMemo(() => {
    const kw = nameFilter.trim().toLowerCase();
    // 范围三态: all=不筛 / queued=ks===Queued / running=ks!==Queued (排队中+运行中=全部)
    const inScope = (r: TaskRow) =>
      queueScope === 'all' ||
      (queueScope === 'queued'
        ? r.kueue_status === 'Queued'
        : r.kueue_status !== 'Queued');
    return rows.filter(
      (r) => inScope(r) && (!kw || (r.name ?? '').toLowerCase().includes(kw)),
    );
  }, [rows, queueScope, nameFilter]);

  // "只看排队"范围: 按 Kueue 真实 min 身位升序; 无身位 (不在队/查失败) 垫底。
  const displayRows = useMemo(() => {
    if (queueScope !== 'queued') return scopeFiltered;
    const pos = (r: TaskRow) => {
      const e = r.k8s_name != null ? queueOrder[r.k8s_name] : undefined;
      return e != null ? e.position : Number.MAX_SAFE_INTEGER;
    };
    return [...scopeFiltered].sort((a, b) => pos(a) - pos(b));
  }, [scopeFiltered, queueScope, queueOrder]);

  const filtered = useMemo(() => {
    const list = displayRows.filter(
      (r) => kindTab === 'all' || r.kind === kindTab,
    );
    // "只看排队"范围: displayRows 已按 Kueue 真实 position 升序排好, 不再二次排序,
    // 保留排队顺序进入表格 (用户点列头时仍由 ProTable 单列 sorter 覆盖)。
    if (queueScope === 'queued') return list;
    // 默认复合排序: 优先级降序 → 同档创建时间降序; 无优先级(null) 垫底。
    // 用户点列头排序时由 ProTable 单列 sorter 覆盖此默认序。
    return list.sort((a, b) => {
      const pa = a.priority_value;
      const pb = b.priority_value;
      if (pa == null && pb != null) return 1;
      if (pa != null && pb == null) return -1;
      if (pa != null && pb != null && pa !== pb) return pb - pa;
      // 同优先级 (或都无): 创建时间降序
      return (b.created_at ?? '').localeCompare(a.created_at ?? '');
    });
  }, [displayRows, kindTab, queueScope]);

  // Excel 式列头筛选选项: 从当前全量数据 (rows) 动态去重生成, 而非硬编码枚举 —
  // 新 phase / 新排队态 / 新创建者出现时自动可筛, 不用改代码。
  const statusFilterOptions = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.status).filter(Boolean) as string[]))
        .sort()
        .map((v) => ({ text: v, value: v })),
    [rows],
  );
  const priorityClassFilterOptions = useMemo(
    () =>
      Array.from(
        new Set(rows.map((r) => r.priority_class).filter(Boolean) as string[]),
      )
        .sort()
        .map((v) => ({ text: v, value: v })),
    [rows],
  );
  const creatorFilterOptions = useMemo(
    () =>
      Array.from(new Set(rows.map((r) => r.creator).filter(Boolean) as string[]))
        .sort()
        .map((v) => ({ text: v, value: v })),
    [rows],
  );

  const columns: ProColumns<TaskRow>[] = [
    {
      title: t('overview.columns.type'),
      dataIndex: 'kind',
      width: 180, // en: "Single-node Inference" 比中文长, 加宽防 Tag 换行
      render: (_, row) => {
        const meta = Object.hasOwn(KIND_META, row.kind) ? KIND_META[row.kind] : undefined;
        return <Tag color={meta?.color}>{meta ? t(meta.labelKey) : row.kind}</Tag>;
      },
    },
    {
      title: t('common:fields.name'),
      dataIndex: 'name',
      width: 240,
      render: (_, row) => (
        <Link to={`/workspaces/${wsId}/${KIND_META[row.kind]?.route}/${row.id}`}>
          {row.name ?? row.id}
        </Link>
      ),
    },
    {
      title: (
        <ColTitle
          text={t('common:fields.status')}
          tip={<div style={{ maxWidth: 280 }}>{t('overview.columns.statusTip')}</div>}
        />
      ),
      dataIndex: 'status',
      width: 180,
      ...(filterEnabled && {
        filters: statusFilterOptions,
        onFilter: (value, row) => row.status === value,
      }),
      // 状态直接显原始 CR phase (不翻译, 与各模块 List 一致); 颜色用 phaseColor 兜底
      // rayjob 的 phase 可能带 " (Deploy Status)" 后缀 → 颜色查表前剥掉; 展示文本仍用原值。
      render: (_, row) => (
        <Badge status={phaseColor(barePhase(row.status ?? undefined))} text={row.status || '-'} />
      ),
    },
    {
      title: (
        <ColTitle
          text={t('overview.columns.queueOrder')}
          tip={t('overview.columns.queueOrderTip')}
        />
      ),
      key: 'queueOrder',
      width: 160, // en: "Queue position" + 问号图标
      render: (_, row) => {
        const e = row.k8s_name != null ? queueOrder[row.k8s_name] : undefined;
        if (e == null) return '-';
        // 主显示取最靠前身位 min+1 (1-based); 多调度单元的明细在展开行 (左侧箭头) 查看。
        return <span>{e.position + 1}</span>;
      },
    },
    {
      title: (
        <ColTitle
          text="GPU"
          tip={t('overview.columns.gpuTip')}
        />
      ),
      dataIndex: 'gpu_spec',
      width: 110,
      render: (v) => <Tag color="blue">{v}</Tag>,
    },
    {
      // 优先级档位 (Kueue WorkloadPriorityClass): queued 行 + 管理员可点改; 否则只读。
      // 列不 ellipsis: 避免把右侧铅笔图标也一起截掉; 长名走 tag 内部截断 + Tooltip
      title: (
        <ColTitle
          text={t('overview.columns.priorityClass')}
          tip={
            <div style={{ maxWidth: 300 }}>
              {t('overview.columns.priorityTipIntro')}
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                <li>{t('overview.columns.priorityTipQueued')}</li>
                <li>{t('overview.columns.priorityTipRunning')}</li>
              </ul>
              {t('overview.columns.priorityTipDict')}
            </div>
          }
        />
      ),
      dataIndex: 'priority_class',
      width: 200,
      sorter: (a: TaskRow, b: TaskRow) =>
        (a.priority_value ?? -Infinity) - (b.priority_value ?? -Infinity),
      ...(filterEnabled && {
        filters: priorityClassFilterOptions,
        filterSearch: true,
        onFilter: (value, row) => row.priority_class === value,
      }),
      render: (_, row) => {
        if (!row.priority_class) return <span>-</span>;
        // 多机推理 (dynamo / llm-d) 暂不支持改优先级 (优先级传播链未打通) → 只读。
        const editable =
          canEdit &&
          row.kueue_status === 'Queued' &&
          row.kind !== 'dynamo' &&
          row.kind !== 'llmd';
        // tag 自身宽度上限 = 列宽 - 铅笔/括号余量, 超出 ellipsis + Tooltip
        const tag = (
          <Tooltip title={row.priority_class}>
            <Tag
              color="orange"
              style={{
                maxWidth: editable ? 140 : 170,
                margin: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                display: 'inline-block',
                verticalAlign: 'middle',
              }}
            >
              {row.priority_class}
              {row.priority_value != null && ` (${row.priority_value})`}
            </Tag>
          </Tooltip>
        );
        if (editable) {
          return (
            <a
              onClick={() => setEditingTask(row)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
            >
              {tag}
              <EditOutlined style={{ flexShrink: 0 }} />
            </a>
          );
        }
        return tag;
      },
    },
    {
      title: t('overview.columns.creator'),
      dataIndex: 'creator',
      width: 160,
      ellipsis: true,
      ...(filterEnabled && {
        filters: creatorFilterOptions,
        filterSearch: true,
        onFilter: (value, row) => row.creator === value,
      }),
    },
    {
      title: t('common:fields.createdAt'),
      dataIndex: 'created_at',
      width: 150,
      sorter: (a: TaskRow, b: TaskRow) =>
        (a.created_at ?? '').localeCompare(b.created_at ?? ''),
      render: (_, row) => (row.created_at ? dayjs(row.created_at).format('MM-DD HH:mm') : '-'),
    },
  ];

  // 排队明细子表格: 展开行渲染每个调度单元的名称 / 身位 / 优先级。
  // 只有多个排队调度单元 (llmd 多 group / 多副本) 才可展开; 单调度单元无明细可看。
  // Workload 名有长度上限 (平台生成时约束), 收窄列宽; ellipsis 兜底超长防挤走后两列。
  const subCols: ColumnsType<QueueWorkload> = [
    {
      title: 'Workload',
      dataIndex: 'name',
      key: 'name',
      width: 240,
      ellipsis: { showTitle: true },
    },
    {
      title: t('overview.columns.queueOrder'),
      dataIndex: 'position',
      key: 'position',
      width: 130,
      render: (p: number) => p + 1,
    },
    { title: t('overview.columns.priority'), dataIndex: 'priority', key: 'priority', width: 90 },
  ];
  const expandable = {
    rowExpandable: (row: TaskRow) => {
      const e = row.k8s_name != null ? queueOrder[row.k8s_name] : undefined;
      return e != null && e.workloads.length > 1;
    },
    expandedRowRender: (row: TaskRow) => {
      const e = row.k8s_name != null ? queueOrder[row.k8s_name] : undefined;
      const data = e?.workloads ?? [];
      return (
        <Table<QueueWorkload>
          size="small"
          rowKey={(w) => w.name || String(w.position)}
          columns={subCols}
          dataSource={data}
          pagination={false}
        />
      );
    },
  };

  // 类型 chip 数量基于"范围+搜索"过滤后的集合, 与表格 base 保持同步。
  const kindCounts = useMemo(
    () => ({
      all: scopeFiltered.length,
      dev: scopeFiltered.filter((r) => r.kind === 'dev').length,
      train: scopeFiltered.filter((r) => r.kind === 'train').length,
      inference: scopeFiltered.filter((r) => r.kind === 'inference').length,
      dynamo: scopeFiltered.filter((r) => r.kind === 'dynamo').length,
      llmd: scopeFiltered.filter((r) => r.kind === 'llmd').length,
      rayjob: scopeFiltered.filter((r) => r.kind === 'rayjob').length,
    }),
    [scopeFiltered],
  );

  // 范围 chip 数量基于全部活跃集合 (不应用 queueScope 自身) + 名称搜索, 否则
  // 切到某范围会让其它 chip 显示自身计数, 失去对比意义。
  // all = 排队中 + 运行中 (互斥完备)。
  const scopeCounts = useMemo(() => {
    const kw = nameFilter.trim().toLowerCase();
    const matched = rows.filter(
      (r) => !kw || (r.name ?? '').toLowerCase().includes(kw),
    );
    const queued = matched.filter((r) => r.kueue_status === 'Queued').length;
    return {
      all: matched.length,
      queued,
      running: matched.length - queued,
    };
  }, [rows, nameFilter]);

  if (forbidden) {
    return (
      <PageContainer header={{ title: t('overview.title') }}>
        <Result
          status="403"
          title={t('overview.forbidden.title')}
          subTitle={t('overview.forbidden.subTitle')}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      header={{ title: t('overview.title') }}
      extra={[
        <Input.Search
          key="search"
          allowClear
          placeholder={t('overview.search')}
          style={{ width: 280 }}
          value={nameFilter}
          onChange={(e) => setNameFilter(e.target.value)}
        />,
        <div key="filter" style={{ position: 'relative' }}>
          <Button
            type={filterEnabled ? 'primary' : 'default'}
            icon={<FilterOutlined />}
            onClick={() => setFilterEnabled((v) => !v)}
          >
            {t('overview.filter')}
          </Button>
          {filterEnabled && (
            <span
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                whiteSpace: 'nowrap',
                fontSize: 12,
                color: '#999',
              }}
            >
              {t('overview.filterLimit')}
            </span>
          )}
        </div>,
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={reload}
        >
          {t('common:actions.refresh')}
        </Button>,
      ]}
    >
      <PageDescription>{t('overview.description')}</PageDescription>
      {/* 两个 tip 合并到一行 (Alert message 槽放两个 chip 标题, description 渲对应内容)。
          chip 充当标签 + 切换器: 同一 chip 再点收起, 不同 chip 互斥切换。 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <a
              onClick={() => setActiveTip((v) => (v === 'rules' ? null : 'rules'))}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                color: activeTip === 'rules' ? '#1677ff' : 'inherit',
                fontWeight: activeTip === 'rules' ? 600 : 400,
              }}
            >
              <span>{t('overview.tips.rules')}</span>
              {activeTip === 'rules' ? (
                <UpOutlined style={{ fontSize: 11 }} />
              ) : (
                <DownOutlined style={{ fontSize: 11 }} />
              )}
            </a>
            <span style={{ color: 'rgba(0,0,0,0.15)' }}>·</span>
            <a
              onClick={() => setActiveTip((v) => (v === 'status' ? null : 'status'))}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                color: activeTip === 'status' ? '#1677ff' : 'inherit',
                fontWeight: activeTip === 'status' ? 600 : 400,
              }}
            >
              <span>{t('overview.tips.status')}</span>
              {activeTip === 'status' ? (
                <UpOutlined style={{ fontSize: 11 }} />
              ) : (
                <DownOutlined style={{ fontSize: 11 }} />
              )}
            </a>
          </div>
        }
        description={
          activeTip === 'rules' ? (
            <div style={{ lineHeight: 1.8 }}>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.rule1" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.rule2" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.rule3" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.rule4" components={{ b: <b /> }} />
                </li>
              </ul>
            </div>
          ) : activeTip === 'status' ? (
            <div style={{ lineHeight: 1.8 }}>
              <div style={{ marginBottom: 8 }}>
                <Trans ns="tasks" i18nKey="overview.tips.queueHeading" components={{ b: <b /> }} />
                <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                  {t('overview.tips.queueScopeNote')}
                </span>
              </div>
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.queue1" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans
                    ns="tasks"
                    i18nKey="overview.tips.queue2"
                    components={{ b: <b />, code: <code /> }}
                  />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.queue3" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.queue4" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.queue5" components={{ b: <b /> }} />
                </li>
              </ul>

              <div style={{ marginBottom: 8 }}>
                <Trans ns="tasks" i18nKey="overview.tips.statusHeading" components={{ b: <b /> }} />
                <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                  {t('overview.tips.statusSourceNote')}
                </span>
              </div>
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>{t('overview.tips.status1')}</li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.status2" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.status3" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="tasks" i18nKey="overview.tips.status4" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans
                    ns="tasks"
                    i18nKey="overview.tips.status5"
                    components={{ b: <b />, code: <code /> }}
                  />
                </li>
              </ul>

              <div
                style={{
                  marginTop: 4,
                  padding: '8px 12px',
                  background: 'rgba(0,0,0,0.02)',
                  borderRadius: 6,
                  fontSize: 12,
                  color: 'rgba(0,0,0,0.55)',
                }}
              >
                <Trans ns="tasks" i18nKey="overview.tips.footnote" components={{ b: <b /> }} />
              </div>
            </div>
          ) : null
        }
      />
      {/* FilterBar 移到表格白色卡片之外 */}
      <FilterBar
        rows={[
          {
            label: t('overview.filters.scope'),
            value: queueScope,
            onChange: (v) => setQueueScope(v as 'all' | 'queued' | 'running'),
            options: [
              { value: 'all', label: t('overview.filters.all'), count: scopeCounts.all },
              { value: 'queued', label: t('overview.filters.queued'), count: scopeCounts.queued },
              { value: 'running', label: t('overview.filters.running'), count: scopeCounts.running },
            ],
          },
          {
            label: t('overview.filters.type'),
            value: kindTab,
            onChange: (v) => setKindTab(v as 'all' | TaskKind),
            options: [
              { value: 'all', label: t('overview.filters.all'), count: kindCounts.all },
              { value: 'dev', label: t(KIND_META.dev.labelKey), count: kindCounts.dev },
              { value: 'train', label: t(KIND_META.train.labelKey), count: kindCounts.train },
              {
                value: 'inference',
                label: t(KIND_META.inference.labelKey),
                count: kindCounts.inference,
              },
              { value: 'rayjob', label: t(KIND_META.rayjob.labelKey), count: kindCounts.rayjob },
              // dynamo / llm-d 菜单临时隐藏 (config/features.ts) → 概览筛选同步藏, 免入口不一致。
              ...(HIDDEN_FEATURE_SEGMENTS.includes('llmd')
                ? []
                : [{ value: 'llmd', label: t(KIND_META.llmd.labelKey), count: kindCounts.llmd }]),
              ...(HIDDEN_FEATURE_SEGMENTS.includes('dynamo')
                ? []
                : [
                    {
                      value: 'dynamo',
                      label: t(KIND_META.dynamo.labelKey),
                      count: kindCounts.dynamo,
                    },
                  ]),
            ],
          },
        ]}
      />
      <ProTable<TaskRow>
        rowKey="id"
        columns={columns}
        dataSource={filtered}
        expandable={expandable}
        loading={loading}
        search={false}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        scroll={{ x: 1380 }}
        toolBarRender={false}
        options={{ reload: false, setting: true, density: true }}
      />

      <ChangePriorityModal
        wsId={wsId}
        task={editingTask}
        onClose={() => setEditingTask(null)}
        onSuccess={() => {
          // 延迟 ~1.5s 重拉, 等 informer 把新 priority_class 落库; 同时刷 Kueue 排队顺序
          window.setTimeout(() => {
            reload();
            reloadQueueOrder();
          }, 1500);
        }}
      />
    </PageContainer>
  );
}
