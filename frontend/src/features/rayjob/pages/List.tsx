import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { Badge, Button, Popconfirm, Space, Tag, Tooltip, message } from 'antd';
import FilterBar from '@/shared/ui/FilterBar';
import PageDescription from '@/shared/ui/PageDescription';
import { FileSearchOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import ColTitle from '@/shared/ui/ColTitle';
import NameCell from '@/shared/ui/NameCell';
import StatusDetailModal from '@/shared/ui/StatusDetailModal';
import dayjs from 'dayjs';
import {
  deleteRayJob,
  getRayJobStatusDetail,
  listRayJob,
  stopRayJob,
} from '../api/client';
import { kueueStatusLabel, kueueStatusColor } from '@/shared/status';
import { barePhase, rayPhaseBadge, RAY_TERMINAL_PHASES } from '../api/types';
import type { RayJobListItem, RayJobScope } from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import { useAppStore } from '@/store';

// 运行时长 (对齐训练): 起点 = started_at (controller 从 CR status.startTime 派生);
// 终点 = ended_at 存在则用它 (任务已结束, 停在结束时刻), 否则用 now (运行中)。
// started_at 缺失 (未开始 / 老任务) → -1 → 显示 "-"。
const durationSec = (
  startedAt?: string | null,
  endedAt?: string | null,
): number => {
  if (!startedAt) return -1;
  const start = dayjs(startedAt);
  const end = endedAt ? dayjs(endedAt) : dayjs();
  return Math.max(0, end.diff(start, 'second'));
};

const formatDuration = (
  startedAt?: string | null,
  endedAt?: string | null,
): string => {
  const sec = durationSec(startedAt, endedAt);
  if (sec < 0) return '-';
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ${min % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
};

// jobStatus (Go controller 权威源, 大写) + 历史 jobDeploymentStatus 兼容 → 见 rayPhaseBadge (api/types)。

export default function RayJobList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['rayjob', 'common']);
  const actionRef = useRef<ActionType>();
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;

  const [scope, setScope] = useState<RayJobScope>(isAdmin ? 'all' : 'mine');
  const [workspaceName, setWorkspaceName] = useState<string>(t('nav.workspace'));
  const [allRows, setAllRows] = useState<RayJobListItem[]>([]);
  const [pageSize, setPageSize] = useState(10);
  const [current, setCurrent] = useState(1);
  const [detailId, setDetailId] = useState<string | null>(null);

  useEffect(() => {
    if (!wsId) return;
    getWorkspace(wsId)
      .then((ws) => setWorkspaceName(ws.display_name))
      .catch(() => undefined);
  }, [wsId]);

  const fetchData = useCallback(async () => {
    if (!wsId) return { data: [] as RayJobListItem[], success: true };
    try {
      const fetchScope: RayJobScope = isAdmin ? 'all' : 'mine';
      const rows = await listRayJob(wsId, { scope: fetchScope });
      setAllRows(rows);
      const filtered =
        isAdmin && scope === 'mine' && currentUser
          ? rows.filter((r) => r.creator_user_id === currentUser.id)
          : rows;
      return { data: filtered, success: true };
    } catch (err) {
      message.error(
        t('messages.loadFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
      return { data: [] as RayJobListItem[], success: false };
    }
  }, [wsId, scope, isAdmin, currentUser, t]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteRayJob(id);
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
      await stopRayJob(id);
      message.success(t('messages.stopped'));
      actionRef.current?.reload();
    } catch (err) {
      message.error(
        t('messages.stopFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    }
  }, [t]);

  const columns: ProColumns<RayJobListItem>[] = useMemo(
    () => [
      {
        title: t('common:fields.name'),
        dataIndex: 'name',
        width: 340,
        render: (_, row) => (
          <NameCell
            to={`/workspaces/${wsId}/rayjob/${row.id}`}
            displayName={row.display_name}
            taskName={row.name}
          />
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
        width: 200,
        render: (_, row) => (
          <Space size={4}>
            <Badge status={rayPhaseBadge[barePhase(row.phase as string)] ?? 'default'} text={(row.phase as string) || '-'} />
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
        title: <ColTitle text={t('fields.queueStatus')} tip={t('list.tips.queueStatus')} />,
        dataIndex: 'kueue_status',
        // 英文 "Queue status" + 提示图标比中文长, 120 → 160
        width: 160,
        render: (_, row) => {
          const label = kueueStatusLabel(row.kueue_status);
          if (!label) return <span style={{ color: '#bbb' }}>-</span>;
          return <Badge status={kueueStatusColor(row.kueue_status)} text={label} />;
        },
      },
      {
        title: <ColTitle text={t('fields.scale')} tip={t('list.tips.scale')} />,
        width: 200,
        search: false,
        render: (_, row) => (
          <Tooltip title={row.worker_instance_type}>
            <Tag color="blue">
              {t('spec.workerCount', { count: row.worker_replicas })} ×{' '}
              {t('spec.gpuCount', { count: row.gpu_per_node })}
            </Tag>
          </Tooltip>
        ),
      },
      {
        title: t('common:fields.duration'),
        width: 100,
        search: false,
        sorter: (a, b) =>
          durationSec(a.started_at, a.ended_at) -
          durationSec(b.started_at, b.ended_at),
        render: (_, row) => formatDuration(row.started_at, row.ended_at),
      },
      {
        title: t('fields.creator'),
        dataIndex: 'creator_display_name',
        width: 160,
        ellipsis: true,
      },
      {
        title: t('common:fields.createdAt'),
        dataIndex: 'created_at',
        width: 160,
        search: false,
        defaultSortOrder: 'descend',
        sorter: (a, b) => dayjs(a.created_at || 0).valueOf() - dayjs(b.created_at || 0).valueOf(),
        render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
      },
      {
        title: t('common:fields.actions'),
        // 英文操作链接更长 (Details / Stop / Clone config / Delete), 180 → 280 且不换行
        width: 280,
        search: false,
        fixed: 'right',
        render: (_, row) => (
          <Space style={{ whiteSpace: 'nowrap' }}>
            <a onClick={() => navigate(`/workspaces/${wsId}/rayjob/${row.id}`)}>{t('actions.details')}</a>
            {!RAY_TERMINAL_PHASES.includes(barePhase(row.phase as string)) && (
              <Popconfirm
                title={t('confirm.stopTitle')}
                description={t('confirm.stopDescList')}
                onConfirm={() => handleStop(row.id)}
                okText={t('common:actions.stop')}
                cancelText={t('common:actions.cancel')}
              >
                <a>{t('common:actions.stop')}</a>
              </Popconfirm>
            )}
            <a onClick={() => navigate(`/workspaces/${wsId}/rayjob/new?cloneFrom=${row.id}`)}>
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
    [wsId, navigate, handleDelete, handleStop, t],
  );

  return (
    <PageContainer
      header={{
        title: t('nav.rayjob'),
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{workspaceName}</a> },
            { title: t('nav.rayjob') },
          ],
        },
      }}
      extra={[
        <Button key="refresh" icon={<ReloadOutlined />} onClick={() => actionRef.current?.reload()}>
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate(`/workspaces/${wsId}/rayjob/new`)}
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
                  onChange: (v: string) => setScope(v as RayJobScope),
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
      <ProTable<RayJobListItem>
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
        scroll={{ x: 1400 }}
        toolBarRender={false}
        options={{ reload: false, setting: true, density: true, fullScreen: true }}
      />
      <StatusDetailModal
        open={detailId !== null}
        title={t('list.statusDetailTitle')}
        detailId={detailId}
        fetcher={getRayJobStatusDetail}
        onClose={() => setDetailId(null)}
      />
    </PageContainer>
  );
}
