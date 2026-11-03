import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { Badge, Button, Popconfirm, Space, Tag, Tooltip, message } from 'antd';
import FilterBar from '@/shared/ui/FilterBar';
import PageDescription from '@/shared/ui/PageDescription';
import { FilterOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import ColTitle from '@/shared/ui/ColTitle';
import NameCell from '@/shared/ui/NameCell';
import dayjs from 'dayjs';
import { deleteLlmd, listLlmd, stopLlmd } from '../api/client';
import { kueueStatusLabel, kueueStatusColor } from '@/shared/status';
import type { LlmdListItem, LlmdScope } from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import { useAppStore } from '@/store';

// 与下方"停止"按钮的可见条件同一套值
const TERMINAL_PHASES = ['failed', 'Stopped'];

/** 终点取 ended_at, 没有就用当前时间。终态却没有 = 老任务, 返回 -1 显示 "-" 而不硬算。 */
const durationSec = (
  createdAt?: string | null,
  endedAt?: string | null,
  phase?: string | null,
): number => {
  if (!createdAt) return -1;
  if (!endedAt && phase && TERMINAL_PHASES.includes(phase)) return -1;
  const end = endedAt ? dayjs(endedAt) : dayjs();
  return Math.max(0, end.diff(dayjs(createdAt), 'second'));
};

const formatDuration = (
  createdAt?: string | null,
  endedAt?: string | null,
  phase?: string | null,
): string => {
  const sec = durationSec(createdAt, endedAt, phase);
  if (sec < 0) return '-';
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ${min % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
};

// Go controller 写 phase + 平台哨兵 Stopped (状态列直接显原始 phase, 这里只取颜色)
const phaseBadge: Record<
  string,
  { status: 'success' | 'processing' | 'default' | 'error' | 'warning' }
> = {
  initializing: { status: 'processing' },
  pending: { status: 'default' },
  successful: { status: 'success' },
  failed: { status: 'error' },
  Stopped: { status: 'warning' },
};

export default function LlmdList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['llmd', 'common']);
  const actionRef = useRef<ActionType>();
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;

  const [scope, setScope] = useState<LlmdScope>(isAdmin ? 'all' : 'mine');
  const [workspaceName, setWorkspaceName] = useState<string>(t('nav.workspace'));
  const [allRows, setAllRows] = useState<LlmdListItem[]>([]);
  const [pageSize, setPageSize] = useState(10);
  const [current, setCurrent] = useState(1);
  // 列头筛选漏斗默认隐藏, 点「筛选」按钮才显 (状态/排队状态/创建者三列)
  const [filterEnabled, setFilterEnabled] = useState(false);

  useEffect(() => {
    if (!wsId) return;
    getWorkspace(wsId)
      .then((ws) => setWorkspaceName(ws.display_name))
      .catch(() => undefined);
  }, [wsId]);

  const fetchData = useCallback(async () => {
    if (!wsId) return { data: [] as LlmdListItem[], success: true };
    try {
      const fetchScope: LlmdScope = isAdmin ? 'all' : 'mine';
      const rows = await listLlmd(wsId, { scope: fetchScope });
      setAllRows(rows);
      const filtered =
        isAdmin && scope === 'mine' && currentUser
          ? rows.filter((r) => r.creator_user_id === currentUser.id)
          : rows;
      return { data: filtered, success: true };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.loadFailed', { error: msg }));
      return { data: [] as LlmdListItem[], success: false };
    }
  }, [wsId, scope, isAdmin, currentUser, t]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteLlmd(id);
      message.success(t('messages.deleted'));
      actionRef.current?.reload();
    } catch (err) {
      message.error(
        t('messages.deleteFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    }
  }, [t]);

  const handleStop = useCallback(async (id: string) => {
    try {
      await stopLlmd(id);
      message.success(t('messages.stopped'));
      actionRef.current?.reload();
    } catch (err) {
      message.error(
        t('messages.stopFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    }
  }, [t]);

  // Excel 式列头筛选选项: 从当前全量数据 (allRows) 动态去重生成, 而非硬编码枚举 —
  // 新 phase / 新排队态 / 新创建者出现时自动可筛, 不用改代码。
  const phaseFilterOptions = useMemo(
    () =>
      Array.from(new Set(allRows.map((r) => r.phase).filter(Boolean)))
        .sort()
        .map((v) => ({ text: v as string, value: v as string })),
    [allRows],
  );
  const kueueFilterOptions = useMemo(
    () =>
      Array.from(new Set(allRows.map((r) => r.kueue_status).filter(Boolean)))
        .sort()
        .map((v) => ({ text: v as string, value: v as string })),
    [allRows],
  );
  const creatorFilterOptions = useMemo(
    () =>
      Array.from(
        new Set(allRows.map((r) => r.creator_display_name).filter(Boolean)),
      )
        .sort()
        .map((v) => ({ text: v, value: v })),
    [allRows],
  );

  const columns: ProColumns<LlmdListItem>[] = useMemo(
    () => [
      {
        title: t('common:fields.name'),
        dataIndex: 'name',
        width: 340,
        render: (_, row) => (
          <NameCell
            to={`/workspaces/${wsId}/llmd/${row.id}`}
            displayName={row.display_name}
            taskName={row.name}
          />
        ),
      },
      {
        title: <ColTitle text={t('common:fields.status')} tip={t('list.tips.status')} />,
        dataIndex: 'phase',
        width: 130,
        ...(filterEnabled && {
          filters: phaseFilterOptions,
          onFilter: (value, row) => row.phase === value,
        }),
        render: (_, row) => {
          // 状态列直接显原始 phase (debug 友好); 颜色取 phaseBadge 命中色, 未命中 default
          const color = phaseBadge[row.phase as string]?.status ?? 'default';
          return <Badge status={color} text={(row.phase as string) || '-'} />;
        },
      },
      {
        title: <ColTitle text={t('fields.queueStatus')} tip={t('list.tips.queueStatus')} />,
        dataIndex: 'kueue_status',
        width: 150,
        ...(filterEnabled && {
          filters: kueueFilterOptions,
          onFilter: (value, row) => row.kueue_status === value,
        }),
        render: (_, row) => {
          const v = row.kueue_status;
          const label = kueueStatusLabel(v);
          if (!label) return <span style={{ color: '#bbb' }}>-</span>;
          return <Badge status={kueueStatusColor(v)} text={label} />;
        },
      },
      {
        title: <ColTitle text={t('fields.scale')} tip={t('list.tips.scale')} />,
        width: 300,
        search: false,
        render: (_, row) => (
          <Tooltip title={row.gpu_instance_type}>
            <Tag color="blue">
              {t('spec.scale', {
                replicas: t('spec.replicaCount', { count: row.replicas }),
                nodes: t('spec.nodeCount', { count: row.nodes_per_replica }),
                gpu: t('spec.gpuCount', { count: row.gpu_per_pod }),
              })}
            </Tag>
          </Tooltip>
        ),
      },
      {
        title: t('common:fields.duration'),
        width: 100,
        search: false,
        render: (_, row) =>
          formatDuration(row.created_at, row.ended_at, row.phase),
      },
      {
        title: t('fields.creator'),
        dataIndex: 'creator_display_name',
        width: 140,
        ellipsis: true,
        ...(filterEnabled && {
          filters: creatorFilterOptions,
          filterSearch: true,
          onFilter: (value, row) => row.creator_display_name === value,
        }),
      },
      {
        title: t('common:fields.createdAt'),
        dataIndex: 'created_at',
        width: 140,
        search: false,
        defaultSortOrder: 'descend',
        sorter: (a, b) => dayjs(a.created_at || 0).valueOf() - dayjs(b.created_at || 0).valueOf(),
        render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
      },
      {
        title: t('common:fields.actions'),
        width: 280,
        search: false,
        fixed: 'right',
        render: (_, row) => (
          <Space>
            <a onClick={() => navigate(`/workspaces/${wsId}/llmd/${row.id}`)}>{t('actions.details')}</a>
            {!['failed', 'Stopped'].includes(row.phase as string) && (
              <Popconfirm
                title={t('confirm.stopTitle')}
                description={t('confirm.stopDesc')}
                onConfirm={() => handleStop(row.id)}
                okText={t('common:actions.stop')}
                cancelText={t('common:actions.cancel')}
              >
                <a>{t('common:actions.stop')}</a>
              </Popconfirm>
            )}
            <a onClick={() => navigate(`/workspaces/${wsId}/llmd/new?cloneFrom=${row.id}`)}>
              {t('actions.cloneConfig')}
            </a>
            <Popconfirm
              title={t('confirm.deleteTitle')}
              description={t('confirm.deleteDescList')}
              onConfirm={() => handleDelete(row.id)}
              okText={t('common:actions.delete')}
              cancelText={t('common:actions.cancel')}
            >
              <a style={{ color: '#f5222d' }}>{t('common:actions.delete')}</a>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [
      wsId,
      navigate,
      handleDelete,
      handleStop,
      filterEnabled,
      phaseFilterOptions,
      kueueFilterOptions,
      creatorFilterOptions,
      t,
    ],
  );

  return (
    <PageContainer
      header={{
        title: t('nav.llmd'),
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{workspaceName}</a> },
            { title: t('nav.llmd') },
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
        <Button key="refresh" icon={<ReloadOutlined />} onClick={() => actionRef.current?.reload()}>
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate(`/workspaces/${wsId}/llmd/new`)}
        >
          {t('list.newButton')}
        </Button>,
      ]}
    >
      <PageDescription>
        {t('list.description')}
      </PageDescription>
      <FilterBar
        rows={[
          ...(isAdmin
            ? [
                {
                  label: t('list.scope.label'),
                  value: scope,
                  onChange: (v: string) => setScope(v as LlmdScope),
                  options: [
                    { value: 'all', label: t('list.scope.all'), count: allRows.length },
                    {
                      value: 'mine',
                      label: t('list.scope.mine'),
                      count: currentUser
                        ? allRows.filter((r) => r.creator_user_id === currentUser.id).length
                        : 0,
                    },
                  ],
                },
              ]
            : []),
        ]}
      />
      <ProTable<LlmdListItem>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={fetchData}
        search={false}
        params={{ scope, wsId }}
        pagination={{
          current,
          pageSize,
          showSizeChanger: true,
          onChange: (p, ps) => {
            setCurrent(p);
            setPageSize(ps);
          },
        }}
        scroll={{ x: 1630 }}
        toolBarRender={false}
        options={{ reload: false, setting: true, density: true, fullScreen: true }}
      />
    </PageContainer>
  );
}
