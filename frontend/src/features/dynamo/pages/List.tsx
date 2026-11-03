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
import dayjs from 'dayjs';
import { deleteDynamo, getDynamoStatusDetail, listDynamo, stopDynamo } from '../api/client';
import StatusDetailModal from '@/shared/ui/StatusDetailModal';
import { kueueStatusLabel, kueueStatusColor } from '@/shared/status';
import type { DynamoListItem, DynamoScope } from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import { useAppStore } from '@/store';

const durationSec = (createdAt?: string | null): number =>
  !createdAt ? -1 : Math.max(0, dayjs().diff(dayjs(createdAt), 'second'));

const formatDuration = (createdAt?: string | null): string => {
  const sec = durationSec(createdAt);
  if (sec < 0) return '-';
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ${min % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
};

// status.state enum (实测) + 平台哨兵 Stopped (状态列直接显原始 phase, 这里只取颜色)
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

export default function DynamoList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['dynamo', 'common']);
  const actionRef = useRef<ActionType>();
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;

  const [scope, setScope] = useState<DynamoScope>(isAdmin ? 'all' : 'mine');
  const [workspaceName, setWorkspaceName] = useState<string>(t('nav.workspace'));
  const [allRows, setAllRows] = useState<DynamoListItem[]>([]);
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
    if (!wsId) return { data: [] as DynamoListItem[], success: true };
    try {
      const fetchScope: DynamoScope = isAdmin ? 'all' : 'mine';
      const rows = await listDynamo(wsId, { scope: fetchScope });
      setAllRows(rows);
      const filtered =
        isAdmin && scope === 'mine' && currentUser
          ? rows.filter((r) => r.creator_user_id === currentUser.id)
          : rows;
      return { data: filtered, success: true };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.loadFailed', { error: msg }));
      return { data: [] as DynamoListItem[], success: false };
    }
  }, [wsId, scope, isAdmin, currentUser, t]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteDynamo(id);
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
      await stopDynamo(id);
      message.success(t('messages.stopped'));
      actionRef.current?.reload();
    } catch (err) {
      message.error(
        t('messages.stopFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    }
  }, [t]);

  const columns: ProColumns<DynamoListItem>[] = useMemo(
    () => [
      {
        title: t('common:fields.name'),
        dataIndex: 'name',
        width: 340,
        render: (_, row) => (
          <NameCell
            to={`/workspaces/${wsId}/dynamo/${row.id}`}
            displayName={row.display_name}
            taskName={row.name}
          />
        ),
      },
      {
        title: <ColTitle text={t('common:fields.status')} tip={t('list.tips.status')} />,
        dataIndex: 'phase',
        width: 130,
        render: (_, row) => {
          // 状态列直接显原始 CR phase (debug 友好, 与推理/训练/开发机一致); 颜色仍取 phaseBadge 命中色, 未命中 default
          const color = phaseBadge[row.phase as string]?.status ?? 'default';
          return (
            <Space size={4}>
              <Badge status={color} text={(row.phase as string) || '-'} />
              <Button
                size="small"
                type="text"
                icon={<FileSearchOutlined />}
                onClick={() => setDetailId(row.id)}
              />
            </Space>
          );
        },
      },
      {
        title: <ColTitle text={t('fields.queueStatus')} tip={t('list.tips.queueStatus')} />,
        dataIndex: 'kueue_status',
        width: 150,
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
          <Tooltip title={row.instance_type}>
            <Tag color="blue">
              {t('spec.scale', {
                replicas: t('spec.replicaCount', { count: row.replicas }),
                nodes: t('spec.nodeCount', { count: row.node_count }),
                gpu: t('spec.gpuCount', { count: row.gpu_per_worker }),
              })}
            </Tag>
          </Tooltip>
        ),
      },
      {
        title: t('common:fields.duration'),
        width: 100,
        search: false,
        render: (_, row) => formatDuration(row.created_at),
      },
      {
        title: t('fields.creator'),
        dataIndex: 'creator_display_name',
        width: 140,
        ellipsis: true,
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
            <a onClick={() => navigate(`/workspaces/${wsId}/dynamo/${row.id}`)}>{t('actions.details')}</a>
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
            <a onClick={() => navigate(`/workspaces/${wsId}/dynamo/new?cloneFrom=${row.id}`)}>
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
        title: t('nav.dynamo'),
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{workspaceName}</a> },
            { title: t('nav.dynamo') },
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
          onClick={() => navigate(`/workspaces/${wsId}/dynamo/new`)}
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
                  onChange: (v: string) => setScope(v as DynamoScope),
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
      <ProTable<DynamoListItem>
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
      <StatusDetailModal
        open={detailId !== null}
        title={t('statusDetailTitle')}
        detailId={detailId}
        fetcher={getDynamoStatusDetail}
        onClose={() => setDetailId(null)}
      />
    </PageContainer>
  );
}
