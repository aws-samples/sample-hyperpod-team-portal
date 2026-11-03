import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer } from '@ant-design/pro-components';
import { useTranslation } from 'react-i18next';
import {
  App,
  Badge,
  Button,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import FilterBar from '@/shared/ui/FilterBar';
import PageDescription from '@/shared/ui/PageDescription';
import type { ColumnsType } from 'antd/es/table';
import {
  CloudServerOutlined,
  FileSearchOutlined,
  FilterOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import ColTitle from '@/shared/ui/ColTitle';
import NameCell from '@/shared/ui/NameCell';
import StatusTip from '@/shared/ui/StatusTip';
import dayjs from 'dayjs';
import {
  deleteDevInstance,
  getDevInstanceStatusDetail,
  startDevInstance,
  stopDevInstance,
} from '../api/client';
import StatusDetailModal from '@/shared/ui/StatusDetailModal';
import {
  phaseColor,
  phaseLabel,
  kueueStatusLabel,
  kueueStatusColor,
} from '@/shared/status';
import type { DevInstanceListItem } from '../api/types';
import { apiFetch, ApiError } from '@/shared/api';
import { useAppStore } from '@/store';

type Scope = 'mine' | 'all';

// Backend returns resource fields on list items as well (contract confirmed by backend owner).
// Local extension to avoid touching the canonical types to this change.
type DevInstanceRow = DevInstanceListItem & {
  cpu_request_millicores?: number;
  memory_request_mib?: number;
};

function listDevInstancesScoped(
  wsId: string,
  scope: Scope,
): Promise<DevInstanceRow[]> {
  return apiFetch<DevInstanceRow[]>(
    `/workspaces/${encodeURIComponent(wsId)}/dev-instances?scope=${scope}`,
  );
}

function formatSpec(row: DevInstanceRow): string {
  const mc = row.cpu_request_millicores ?? 0;
  // 2000mc → "2c"; 500mc → "0.5c"; keep 1 decimal when not whole.
  const cores = mc / 1000;
  const cpuLabel = Number.isInteger(cores) ? `${cores}c` : `${cores.toFixed(1)}c`;
  const memGib = Math.round((row.memory_request_mib ?? 0) / 1024);
  const gpu = row.gpu_count ?? 0;
  const ebs = row.storage_size_gib ?? 0;
  return `${cpuLabel} · ${memGib}G · ${gpu} GPU · ${ebs}G EBS`;
}

const POLL_MS = 30_000;

function formatDuration(from: string | null | undefined): string {
  if (!from) return '-';
  const diff = dayjs().diff(dayjs(from), 'second');
  if (diff < 60) return `${diff}s`;
  const min = Math.floor(diff / 60);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ${min % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export default function DevList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['devinstance', 'common']);
  const { message } = App.useApp();

  const [data, setData] = useState<DevInstanceRow[]>([]);
  // "我的" id 集: 走后端 scope=mine (已含"我创建的 ∪ 分享给我的")。超管的 data 是
  // all, 不能用 creator===me 派生 mine — 那样会漏掉分享给我的 (creator≠我)。
  const [mineIds, setMineIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  // 登录用户取全局 store (AuthGate 已注入), 不再每页异步重拉 —— 旧写法首帧
  // currentUser=null → isAdmin=false → 默认 mine + 只拉 mine, 等 user 回来才切 all,
  // 表现为"先显 2 个/只显自己, 过一会儿才全部"的竞态。store 取值首帧即就绪。
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;
  const [scope, setScope] = useState<Scope>(isAdmin ? 'all' : 'mine');
  const [detailId, setDetailId] = useState<string | null>(null);
  // 列头筛选漏斗默认隐藏, 点「筛选」按钮才显 (状态/排队状态/创建者三列)
  const [filterEnabled, setFilterEnabled] = useState(false);

  const load = useCallback(
    async (silent = false) => {
      if (!wsId) return;
      if (!silent) setLoading(true);
      try {
        // 超管: 并行拉 all (给"全部" tab) + mine (给"我的" tab, 后端已含分享给我的)。
        // 切 scope 不触发请求 (两份都在手)。非 admin: 后端只返 mine (含分享), 一份够。
        if (isAdmin) {
          const [allRows, mineRows] = await Promise.all([
            listDevInstancesScoped(wsId, 'all'),
            listDevInstancesScoped(wsId, 'mine'),
          ]);
          setData(allRows);
          setMineIds(new Set(mineRows.map((r) => r.id)));
        } else {
          const rows = await listDevInstancesScoped(wsId, 'mine');
          setData(rows);
          setMineIds(new Set(rows.map((r) => r.id)));
        }
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : t('common:messages.loadFailed');
        if (!silent) message.error(msg);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [wsId, isAdmin, message, t],
  );

  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const handleStop = async (row: DevInstanceRow) => {
    try {
      await stopDevInstance(row.id);
      message.success(t('messages.stopSentNamed', { name: row.display_name }));
      load(true);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('messages.stopFailed'));
    }
  };

  const handleStart = async (row: DevInstanceRow) => {
    try {
      await startDevInstance(row.id);
      message.success(t('messages.startSentNamed', { name: row.display_name }));
      load(true);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('messages.startFailed'));
    }
  };

  const handleDelete = async (row: DevInstanceRow) => {
    try {
      await deleteDevInstance(row.id);
      message.success(t('messages.deletedNamed', { name: row.display_name }));
      load(true);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('messages.deleteFailed'));
    }
  };

  // Excel 式列头筛选选项: 从当前全量数据 (data) 动态去重生成, 而非硬编码枚举 —
  // 新 phase / 新排队态 / 新创建者出现时自动可筛, 不用改代码。
  const phaseFilterOptions = useMemo(
    () =>
      Array.from(new Set(data.map((r) => r.phase).filter(Boolean)))
        .sort()
        .map((v) => ({ text: v, value: v })),
    [data],
  );
  const kueueFilterOptions = useMemo(
    () =>
      Array.from(new Set(data.map((r) => r.kueue_status).filter(Boolean)))
        .sort()
        .map((v) => ({ text: v as string, value: v as string })),
    [data],
  );
  const creatorFilterOptions = useMemo(
    () =>
      Array.from(
        new Set(data.map((r) => r.creator_display_name).filter(Boolean)),
      )
        .sort()
        .map((v) => ({ text: v, value: v })),
    [data],
  );

  const columns: ColumnsType<DevInstanceRow> = useMemo(
    () => [
      {
        title: t('common:fields.name'),
        dataIndex: 'name',
        width: 340,
        render: (_, row) => (
          <NameCell
            to={`/workspaces/${wsId}/dev/${row.id}`}
            displayName={row.display_name || row.name}
            taskName={row.k8s_workspace_name || row.name}
          />
        ),
      },
      {
        title: (
          <ColTitle
            text={t('list.columns.template')}
            tip={t('list.tips.template')}
          />
        ),
        dataIndex: 'template_name',
        width: 130,
        render: (_, row) => (
          <Tag color={row.app_type === 'code-editor' ? 'purple' : 'geekblue'}>
            {row.app_type}
          </Tag>
        ),
      },
      {
        title: (
          <ColTitle
            text={t('list.columns.spec')}
            tip={t('list.tips.spec')}
          />
        ),
        width: 240,
        render: (_, row) => (
          <Tag color="blue" icon={<CloudServerOutlined />}>
            {formatSpec(row)}
          </Tag>
        ),
      },
      {
        title: (
          <ColTitle
            text={t('common:fields.status')}
            tip={t('list.tips.status')}
          />
        ),
        dataIndex: 'phase',
        width: 190,
        ...(filterEnabled && {
          filters: phaseFilterOptions,
          onFilter: (value, row) => row.phase === value,
        }),
        render: (_, row) => (
          <Space size={4}>
            {/* 状态列直接显原始 CR phase (debug 友好); 颜色仍用 phaseColor 兜底, 中文翻译留给状态详情弹窗/总览不需要 */}
            <Badge status={phaseColor(row.phase)} text={row.phase || '-'} />
            <Button
              size="small"
              type="text"
              icon={<FileSearchOutlined />}
              onClick={() => setDetailId(row.id)}
            />
          </Space>
        ),
      },
      {
        title: (
          <ColTitle
            text={t('list.columns.queueStatus')}
            tip={t('list.tips.queueStatus')}
          />
        ),
        dataIndex: 'kueue_status',
        width: 180,
        ...(filterEnabled && {
          filters: kueueFilterOptions,
          onFilter: (value, row) => row.kueue_status === value,
        }),
        render: (v: string | null | undefined) => {
          // kueue_status 六态 (Workload镜像) → 原始英文值 + 语义分色; 无值显 -
          const label = kueueStatusLabel(v);
          if (!label) return <span style={{ color: '#bbb' }}>-</span>;
          const badge = <Badge status={kueueStatusColor(v)} text={label} />;
          return v === 'Queued' ? (
            <Tooltip title={t('common:kueueStatus.queuedTip')}>{badge}</Tooltip>
          ) : (
            badge
          );
        },
      },
      {
        title: t('common:fields.duration'),
        width: 120,
        render: (_, row) =>
          (row.phase || '').includes('Available') ? formatDuration(row.started_at) : '-',
      },
      {
        title: t('list.columns.creator'),
        dataIndex: 'creator_display_name',
        width: 160,
        ...(filterEnabled && {
          filters: creatorFilterOptions,
          filterSearch: true,
          onFilter: (value, row) => row.creator_display_name === value,
        }),
        render: (_, row) => {
          const isMe =
            !!currentUser && row.creator_user_id === currentUser.id;
          const label = row.creator_display_name || row.creator_user_id;
          return (
            <Tooltip title={isMe ? t('list.creatorMeTooltip', { name: label }) : label}>
              <Typography.Text ellipsis style={{ maxWidth: 140 }}>
                {label}
                {isMe && (
                  <Typography.Text type="secondary"> {t('list.meTag')}</Typography.Text>
                )}
              </Typography.Text>
            </Tooltip>
          );
        },
      },
      {
        title: t('common:fields.createdAt'),
        dataIndex: 'created_at',
        width: 170,
        render: (v) =>
          v ? (
            <Tooltip title={dayjs(v as string).format('YYYY-MM-DD HH:mm:ss')}>
              <span>{dayjs(v as string).fromNow?.() ?? dayjs(v as string).format('MM-DD HH:mm')}</span>
            </Tooltip>
          ) : (
            '-'
          ),
      },
      {
        title: t('common:fields.actions'),
        // 英文操作链接更长 (Details / Clone config / Stop / Delete), 200 → 280 且不换行
        width: 280,
        fixed: 'right',
        render: (_, row) => {
          const running = (row.phase || '').includes('Available');
          const stopped = (row.phase || '').includes('Stopped');
          // 被分享行 (creator ≠ 我): 只保留 详情/克隆, 隐藏 停止/启动/删除 (写操作限 creator)。
          const isMine = !!currentUser && row.creator_user_id === currentUser.id;
          return (
            <Space style={{ whiteSpace: 'nowrap' }}>
              <a onClick={() => navigate(`/workspaces/${wsId}/dev/${row.id}`)}>
                {t('actions.details')}
              </a>
              <a onClick={() => navigate(`/workspaces/${wsId}/dev/new?cloneFrom=${row.id}`)}>
                {t('actions.cloneConfig')}
              </a>
              {isMine && running && (
                <Popconfirm
                  title={t('confirm.stopTitle')}
                  description={t('confirm.stopDesc')}
                  onConfirm={() => handleStop(row)}
                  okText={t('common:actions.stop')}
                  cancelText={t('common:actions.cancel')}
                >
                  <a>{t('common:actions.stop')}</a>
                </Popconfirm>
              )}
              {isMine && stopped && (
                <a onClick={() => handleStart(row)}>{t('common:actions.start')}</a>
              )}
              {isMine && (
                <Popconfirm
                  title={t('confirm.deleteTitle', { name: row.display_name })}
                  description={t('confirm.deleteDesc')}
                  okType="danger"
                  onConfirm={() => handleDelete(row)}
                  okText={t('common:actions.delete')}
                  cancelText={t('common:actions.cancel')}
                >
                  <a style={{ color: '#f5222d' }}>{t('common:actions.delete')}</a>
                </Popconfirm>
              )}
            </Space>
          );
        },
      },
    ],
    [
      wsId,
      navigate,
      currentUser,
      filterEnabled,
      phaseFilterOptions,
      kueueFilterOptions,
      creatorFilterOptions,
      t,
    ],
  );

  // "我的" = mineIds (后端 scope=mine, 含我创建的 ∪ 分享给我的)。不再用 creator===me
  // 派生 — 否则超管漏掉分享给自己的 (creator≠我)。普通成员 data 即 mine, 两者相等。
  const allCount = data.length;
  const myCount = useMemo(
    () => data.filter((r) => mineIds.has(r.id)).length,
    [data, mineIds],
  );
  // scope 过滤后的子集。状态/排队状态/创建者的筛选交给列头 Excel 式 filters (见 columns)。
  const visibleData = useMemo(() => {
    if (!isAdmin || scope === 'all') return data;
    return data.filter((r) => mineIds.has(r.id));
  }, [data, isAdmin, scope, mineIds]);

  return (
    <PageContainer
      header={{
        title: t('nav.devInstance'),
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{t('nav.workspace')}</a> },
            { title: t('nav.devInstance') },
          ],
        },
      }}
      extra={[
        <div key="filter" style={{ position: 'relative' }}>
          <Button
            type={filterEnabled ? 'primary' : 'default'}
            icon={<FilterOutlined />}
            onClick={() => setFilterEnabled((v) => !v)}
          >
            {t('list.filter')}
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
              {t('list.filterHint')}
            </span>
          )}
        </div>,
        <Button key="refresh" icon={<ReloadOutlined />} onClick={() => load()}>
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate(`/workspaces/${wsId}/dev/new`)}
        >
          {t('list.newButton')}
        </Button>,
      ]}
    >
      <PageDescription>
        {t('list.description')}
      </PageDescription>
      <StatusTip
        phaseSource="SageMaker Spaces Workspace CR.status.conditions[].type"
        phaseRows={[
          {
            value: 'Progressing',
            label: phaseLabel('Progressing'),
            detail: t('list.statusTip.progressing'),
          },
          {
            value: 'Available',
            label: phaseLabel('Available'),
            detail: t('list.statusTip.available'),
          },
          {
            value: 'Stopped',
            label: phaseLabel('Stopped'),
            detail: t('list.statusTip.stopped'),
          },
          {
            value: 'Degraded',
            label: phaseLabel('Degraded'),
            detail: t('list.statusTip.degraded'),
          },
        ]}
      />
      {/* FilterBar · 范围 (admin)。任务状态 / 排队状态 / 创建者筛选交给列头 Excel 式 filters */}
      <FilterBar
        rows={[
          ...(isAdmin
            ? [
                {
                  label: t('list.scope.label'),
                  value: scope,
                  onChange: (v: string) => setScope(v as Scope),
                  options: [
                    { value: 'all', label: t('list.scope.all'), count: allCount },
                    { value: 'mine', label: t('list.scope.mine'), count: myCount },
                  ],
                },
              ]
            : []),
        ]}
      />
      <Table<DevInstanceRow>
        rowKey="id"
        columns={columns}
        dataSource={visibleData}
        loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        scroll={{ x: 1280 }}
      />
      <StatusDetailModal
        open={detailId !== null}
        title={t('statusDetailTitle')}
        detailId={detailId}
        fetcher={getDevInstanceStatusDetail}
        onClose={() => setDetailId(null)}
      />
    </PageContainer>
  );
}
