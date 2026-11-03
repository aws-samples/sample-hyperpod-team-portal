import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Popconfirm,
  Space,
  Tag,
  Tooltip,
  message,
} from 'antd';
import FilterBar from '@/shared/ui/FilterBar';
import PageDescription from '@/shared/ui/PageDescription';
import {
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
  deleteInference,
  getInferenceStatusDetail,
  listInferences,
  stopInference,
} from '../api/client';
import StatusDetailModal from '@/shared/ui/StatusDetailModal';
import { kueueStatusLabel, kueueStatusColor } from '@/shared/status';
import type {
  InferenceListItem,
  InferenceScope,
} from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import { useAppStore } from '@/store';

// 与下方"停止"按钮的可见条件同一套值
const TERMINAL_PHASES = ['DeploymentFailed', 'Stopped', 'Deleted'];

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

// 只取状态点颜色; 状态文字直接显示原始 CR phase (不翻译), 故这里不存文案。
const phaseBadge: Record<
  string,
  { status: 'success' | 'processing' | 'default' | 'error' | 'warning' }
> = {
  // 原始 deploymentObjectOverallState / state 值 (不再归一)
  DeploymentComplete: { status: 'success' },
  DeploymentInProgress: { status: 'processing' },
  DeploymentPending: { status: 'default' },
  DeploymentFailed: { status: 'error' },
  // 业务哨兵 (CR 不存在时 sync 写)
  Stopped: { status: 'warning' },
  Deleted: { status: 'default' },
};

export default function InferenceList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['inference', 'common', 'status']);
  const actionRef = useRef<ActionType>();
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;

  const [scope, setScope] = useState<InferenceScope>(isAdmin ? 'all' : 'mine');
  const [workspaceName, setWorkspaceName] = useState<string>(t('nav.workspace'));
  const [detailId, setDetailId] = useState<string | null>(null);
  // 列头筛选漏斗默认隐藏, 点「筛选」按钮才显 (状态/排队状态/框架/创建者四列)
  const [filterEnabled, setFilterEnabled] = useState(false);

  useEffect(() => {
    if (!wsId) return;
    getWorkspace(wsId)
      .then((ws) => setWorkspaceName(ws.display_name))
      .catch(() => undefined);
  }, [wsId]);

  // 一次性 sync flag · "强制刷新" 按钮设 true, fetchData 消费一次后回 false.
  const syncOnceRef = useRef(false);

  const fetchData = useCallback(async () => {
    if (!wsId) return { data: [] as InferenceListItem[], success: true };
    const sync = syncOnceRef.current;
    syncOnceRef.current = false;
    try {
      // admin 拉 all (前端再按 scope 过滤, 让"全部/我的"两个 chip 都能显数量);
      // 普通成员后端只返 mine, fetchScope 取 mine 即可。
      const fetchScope: InferenceScope = isAdmin ? 'all' : 'mine';
      const rows = await listInferences(wsId, { scope: fetchScope, sync });
      setAllRows(rows);
      const scopeFiltered =
        isAdmin && scope === 'mine' && currentUser
          ? rows.filter((r) => r.creator_user_id === currentUser.id)
          : rows;
      // 不传 total → ProTable 客户端分页 (自己切片), 否则它当服务端分页, 切 pageSize 失效
      // 状态/排队状态/框架/创建者的筛选交给列头 Excel 式 filters (antd Table 内置, 见 columns)
      return { data: scopeFiltered, success: true };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.loadFailed', { error: msg }));
      return { data: [] as InferenceListItem[], success: false };
    }
  }, [wsId, scope, isAdmin, currentUser, t]);

  // 分页受控: 翻页 / 切每页条数不被刷新冲掉
  const [pageSize, setPageSize] = useState(10);
  const [current, setCurrent] = useState(1);
  // admin 始终拉 all (前端按 creator_user_id 派生 mine), allCount/myCount 都可见。
  const [allRows, setAllRows] = useState<InferenceListItem[]>([]);


  // 自动 sync 已移除 (会打断翻页/切页 + 终态轮询浪费)。状态更新靠「强制刷新」手动触发。

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteInference(id);
      message.success(t('messages.deleted'));
      actionRef.current?.reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.deleteFailed', { error: msg }));
    }
  }, [t]);

  const handleStop = useCallback(async (id: string) => {
    try {
      await stopInference(id);
      message.success(t('messages.stopped'));
      actionRef.current?.reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.stopFailed', { error: msg }));
    }
  }, [t]);

  // Excel 式列头筛选选项: 从当前全量数据 (allRows) 动态去重生成, 而非硬编码枚举 —
  // 新 phase / 新排队态 / 新框架 / 新创建者出现时自动可筛, 不用改代码。
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
  const frameworkFilterOptions = useMemo(
    () =>
      Array.from(new Set(allRows.map((r) => r.framework).filter(Boolean)))
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

  const columns: ProColumns<InferenceListItem>[] = useMemo(
    () => [
      {
        title: t('common:fields.name'),
        dataIndex: 'name',
        width: 340,
        sorter: (a, b) =>
          (a.display_name || a.name || '').localeCompare(
            b.display_name || b.name || '',
          ),
        render: (_, row) => (
          <NameCell
            to={`/workspaces/${wsId}/inference/${row.id}`}
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
        // 内容为原始 CR phase 英文串 (最长 DeploymentInProgress 20 字符) + 状态点 + 放大镜按钮,
        // 170 放不下 DeploymentInProgress, 加宽避免截断。
        width: 220,
        sorter: (a, b) => (a.phase || '').localeCompare(b.phase || ''),
        ...(filterEnabled && {
          filters: phaseFilterOptions,
          onFilter: (value, row) => row.phase === value,
        }),
        render: (_, row) => {
          // 状态列直接显原始 CR phase (debug 友好, 与训练/开发机一致); 颜色仍取 phaseBadge 命中色, 未命中 default
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
        title: (
          <ColTitle
            text={t('fields.queueStatus')}
            tip={t('list.tips.queueStatus')}
          />
        ),
        dataIndex: 'kueue_status',
        // 英文列头 "Queue status" + 提示图标更长, 120 → 170
        width: 170,
        ...(filterEnabled && {
          filters: kueueFilterOptions,
          onFilter: (value, row) => row.kueue_status === value,
        }),
        render: (_, row) => {
          // kueue_status 六态 (Workload镜像) → 原始英文值 + 语义分色; 无值显 -
          const v = row.kueue_status;
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
        title: (
          <ColTitle
            text={t('fields.framework')}
            tip={t('list.tips.framework')}
          />
        ),
        dataIndex: 'framework',
        // 英文列头 "Framework" + 提示图标更长, 90 → 120
        width: 120,
        ...(filterEnabled && {
          filters: frameworkFilterOptions,
          onFilter: (value, row) => row.framework === value,
        }),
        render: (_, row) => (
          <Tag color="purple">{(row.framework || 'sglang').toUpperCase()}</Tag>
        ),
      },
      {
        title: (
          <ColTitle
            text={t('fields.spec')}
            tip={t('list.tips.spec')}
          />
        ),
        width: 160,
        search: false,
        render: (_, row) => (
          <Tooltip title={row.instance_type}>
            <Tag color="blue">
              {row.replicas} × {t('spec.gpuCount', { count: row.gpu_per_replica })}
            </Tag>
          </Tooltip>
        ),
      },
      {
        title: t('common:fields.duration'),
        width: 120,
        search: false,
        sorter: (a, b) =>
          durationSec(a.created_at, a.ended_at, a.phase as string) -
          durationSec(b.created_at, b.ended_at, b.phase as string),
        render: (_, row) =>
          formatDuration(row.created_at, row.ended_at, row.phase as string),
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
        sorter: (a, b) =>
          dayjs(a.created_at || 0).valueOf() -
          dayjs(b.created_at || 0).valueOf(),
        render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
      },
      {
        title: t('common:fields.actions'),
        // 英文操作链接更长 (Details / Stop / Clone config / Delete), 200 → 280 且不换行
        width: 280,
        search: false,
        fixed: 'right',
        render: (_, row) => (
          <Space>
            <a
              onClick={() => navigate(`/workspaces/${wsId}/inference/${row.id}`)}
            >
              {t('actions.details')}
            </a>
            {!['DeploymentFailed', 'Stopped', 'Deleted'].includes(row.phase as string) && (
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
            <a
              onClick={() =>
                navigate(`/workspaces/${wsId}/inference/new?cloneFrom=${row.id}`)
              }
            >
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
      frameworkFilterOptions,
      creatorFilterOptions,
      t,
    ],
  );

  return (
    <PageContainer
      header={{
        title: t('nav.inference'),
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>
                  {workspaceName}
                </a>
              ),
            },
            { title: t('nav.inference') },
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
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          onClick={() => {
            syncOnceRef.current = true;
            actionRef.current?.reload();
          }}
        >
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate(`/workspaces/${wsId}/inference/new`)}
        >
          {t('list.newButton')}
        </Button>,
      ]}
    >
      <PageDescription>
        {t('list.description')}
      </PageDescription>
      <StatusTip
        phaseSource={t('list.statusTip.phaseSource')}
        phaseRows={[
          {
            value: 'DeploymentPending',
            label: t('status:phase.pendingDeploy'),
            detail: t('list.statusTip.pending.detail'),
          },
          {
            value: 'DeploymentInProgress',
            label: t('status:phase.deploying'),
            detail: t('list.statusTip.deploying.detail'),
          },
          {
            value: 'DeploymentComplete',
            label: t('status:phase.running'),
            detail: t('list.statusTip.running.detail'),
          },
          {
            value: 'DeploymentFailed',
            label: t('list.statusTip.failed.label'),
            detail: t('list.statusTip.failed.detail'),
          },
          {
            value: 'Stopped',
            label: t('status:phase.stopped'),
            detail: t('list.statusTip.stopped.detail'),
          },
        ]}
      />
      {/* FilterBar · 范围 (admin)。任务状态 / 排队状态 / 框架 / 创建者筛选交给列头 Excel 式 filters */}
      <FilterBar
        rows={[
          ...(isAdmin
            ? [
                {
                  label: t('list.scope.label'),
                  value: scope,
                  onChange: (v: string) => setScope(v as InferenceScope),
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
      <ProTable<InferenceListItem>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={fetchData}
        search={false}
        // wsId 进 params: 切换工作空间时 params 变 → ProTable 自动重拉
        // (ProTable 只监听 params 变化, 不监听 request/fetchData 闭包更新)
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
        scroll={{ x: 1700 }}
        toolBarRender={false}
        options={{
          reload: false,
          setting: true,
          density: true,
          fullScreen: true,
        }}
      />
      <StatusDetailModal
        open={detailId !== null}
        title={t('statusDetailTitle')}
        detailId={detailId}
        fetcher={getInferenceStatusDetail}
        onClose={() => setDetailId(null)}
      />
    </PageContainer>
  );
}
