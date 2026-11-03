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
  deleteTrainingJob,
  getTrainingStatusDetail,
  listTrainingJobs,
  stopTrainingJob,
} from '../api/client';
import StatusDetailModal from '@/shared/ui/StatusDetailModal';
import {
  phaseColor,
  phaseLabel,
  kueueStatusLabel,
  kueueStatusColor,
} from '@/shared/status';
import type {
  TrainingJobListItem,
  TrainingScope,
} from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import { useAppStore } from '@/store';

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

export default function TrainingList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['training', 'common']);
  const actionRef = useRef<ActionType>();
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;

  const [scope, setScope] = useState<TrainingScope>(isAdmin ? 'all' : 'mine');
  const [workspaceName, setWorkspaceName] = useState<string>(t('nav.workspace'));
  const [detailId, setDetailId] = useState<string | null>(null);
  // 列头筛选漏斗默认隐藏, 点「筛选」按钮才显 (状态/排队状态/创建者三列)
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
    if (!wsId) return { data: [] as TrainingJobListItem[], success: true };
    const sync = syncOnceRef.current;
    syncOnceRef.current = false;
    try {
      // 超管: 并行拉 all + mine (后端 mine 已含"我创建的 ∪ 分享给我的")。不能用
      // creator===me 派生 mine — 超管会漏掉分享给自己的 (creator≠我)。
      // 普通成员: 后端只返 mine (含分享), 一份够, mineIds = 全部。
      let rows: TrainingJobListItem[];
      let mineIdSet: Set<string>;
      if (isAdmin) {
        const [allR, mineR] = await Promise.all([
          listTrainingJobs(wsId, { scope: 'all', sync }),
          listTrainingJobs(wsId, { scope: 'mine' }),
        ]);
        rows = allR;
        mineIdSet = new Set(mineR.map((r) => r.id));
      } else {
        rows = await listTrainingJobs(wsId, { scope: 'mine', sync });
        mineIdSet = new Set(rows.map((r) => r.id));
      }
      setAllRows(rows);
      setMineIds(mineIdSet);
      const scopeFiltered =
        isAdmin && scope === 'mine'
          ? rows.filter((r) => mineIdSet.has(r.id))
          : rows;
      // 不传 total → ProTable 客户端分页 (自己切片), 否则它当服务端分页, 切 pageSize 失效
      // 状态/排队状态/创建者的筛选交给列头 Excel 式 filters (antd Table 内置, 见 columns)
      return { data: scopeFiltered, success: true };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.loadFailed', { error: msg }));
      return { data: [] as TrainingJobListItem[], success: false };
    }
  }, [wsId, scope, isAdmin, t]);

  // 分页受控: 翻页 / 切每页条数不被刷新冲掉
  const [pageSize, setPageSize] = useState(10);
  const [current, setCurrent] = useState(1);
  // admin 拉 all (给"全部" chip), mineIds 来自后端 scope=mine (含分享给我的)。
  const [allRows, setAllRows] = useState<TrainingJobListItem[]>([]);
  const [mineIds, setMineIds] = useState<Set<string>>(new Set());

  // 自动 sync 已移除 (会打断翻页/切页 + 终态轮询浪费)。状态更新靠「强制刷新」手动触发。

  const handleStop = useCallback(async (id: string) => {
    try {
      await stopTrainingJob(id);
      message.success(t('messages.stopped'));
      actionRef.current?.reload();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(t('messages.stopFailed', { error: msg }));
    }
  }, [t]);

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteTrainingJob(id);
        message.success(t('messages.deleted'));
        actionRef.current?.reload();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        message.error(t('messages.deleteFailed', { error: msg }));
      }
    },
    [t],
  );

  // Excel 式列头筛选选项: 从当前全量数据 (allRows) 动态去重生成, 而非硬编码枚举 —
  // 新 phase / 新排队态 / 新创建者出现时自动可筛, 不用改代码。
  const phaseFilterOptions = useMemo(
    () =>
      Array.from(new Set(allRows.map((r) => r.phase).filter(Boolean)))
        .sort()
        .map((v) => ({ text: v, value: v })),
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

  const columns: ProColumns<TrainingJobListItem>[] = useMemo(
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
            to={`/workspaces/${wsId}/training/${row.id}`}
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
        width: 170,
        sorter: (a, b) => (a.phase || '').localeCompare(b.phase || ''),
        ...(filterEnabled && {
          filters: phaseFilterOptions,
          onFilter: (value, row) => row.phase === value,
        }),
        render: (_, row) => (
          <Space size={4}>
            {/* 状态列直接显原始 CR phase (debug 友好); 颜色用 phaseColor 兜底, 不翻译 */}
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
            text={t('fields.queueStatus')}
            tip={t('list.tips.queueStatus')}
          />
        ),
        dataIndex: 'kueue_status',
        // 英文 "Queue status" + 提示图标比中文长, 120 → 160
        width: 160,
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
            text={t('fields.spec')}
            tip={t('list.tips.spec')}
          />
        ),
        width: 140,
        search: false,
        sorter: (a, b) =>
          a.node_count * a.gpu_per_node - b.node_count * b.gpu_per_node,
        render: (_, row) => (
          <Tooltip
            title={`${(row.cpu_per_node_millicores / 1000).toFixed(1)} ${t('spec.unitCore', { count: Number((row.cpu_per_node_millicores / 1000).toFixed(1)) })} · ${(row.memory_per_node_mib / 1024).toFixed(1)} GiB`}
          >
            <Tag color="blue">
              {row.node_count} × {t('spec.gpuCount', { count: row.gpu_per_node })}
            </Tag>
          </Tooltip>
        ),
      },
      {
        title: t('fields.creator'),
        dataIndex: 'creator_display_name',
        width: 160,
        ellipsis: true,
        sorter: (a, b) =>
          (a.creator_display_name || '').localeCompare(
            b.creator_display_name || '',
          ),
        ...(filterEnabled && {
          filters: creatorFilterOptions,
          filterSearch: true,
          onFilter: (value, row) => row.creator_display_name === value,
        }),
      },
      {
        title: t('common:fields.duration'),
        width: 120,
        search: false,
        sorter: (a, b) =>
          durationSec(a.started_at, a.ended_at) -
          durationSec(b.started_at, b.ended_at),
        render: (_, row) => formatDuration(row.started_at, row.ended_at),
      },
      {
        title: t('common:fields.createdAt'),
        dataIndex: 'created_at',
        width: 160,
        search: false,
        defaultSortOrder: 'descend',
        sorter: (a, b) =>
          dayjs(a.created_at || 0).valueOf() -
          dayjs(b.created_at || 0).valueOf(),
        render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
      },
      {
        title: t('common:fields.actions'),
        // 英文操作链接更长 (Details / Clone config / Stop / Delete), 210 → 280 且不换行
        width: 280,
        search: false,
        fixed: 'right',
        render: (_, row) => {
          // 被分享行 (creator ≠ 我): 只保留 详情/克隆, 隐藏 停止/删除 (写操作限 creator)。
          const isMine = !!currentUser && row.creator_user_id === currentUser.id;
          return (
            <Space style={{ whiteSpace: 'nowrap' }}>
              <a
                onClick={() => navigate(`/workspaces/${wsId}/training/${row.id}`)}
              >
                {t('actions.details')}
              </a>
              <a
                onClick={() =>
                  navigate(`/workspaces/${wsId}/training/new?cloneFrom=${row.id}`)
                }
              >
                {t('actions.cloneConfig')}
              </a>
              {/* 停止: 仅 creator 本人 + 非终态. 释放 GPU + 留记录.
                  成功完成有 Complete/Completed/Succeeded 三个同义词 (取决于 operator 写哪个
                  condition type); Complete 靠子串吃掉前两个, Succeeded 不含该子串须单列. */}
              {isMine &&
                !/Complete|Succeeded|Failed|Stopped/i.test(row.phase || '') && (
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
              {isMine && (
                <Popconfirm
                  title={t('confirm.deleteTitle')}
                  description={t('confirm.deleteDescList')}
                  onConfirm={() => handleDelete(row.id)}
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
      handleDelete,
      handleStop,
      currentUser,
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
        title: t('nav.training'),
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>
                  {workspaceName}
                </a>
              ),
            },
            { title: t('nav.training') },
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
            syncOnceRef.current = true;  // 强制 sync 一次, 拉真 K8s 状态
            actionRef.current?.reload();
          }}
        >
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate(`/workspaces/${wsId}/training/new`)}
        >
          {t('list.newButton')}
        </Button>,
      ]}
    >
      <PageDescription>
        {t('list.description')}
      </PageDescription>
      <StatusTip
        phaseSource="HyperPodPyTorchJob CR.status.conditions[].type"
        phaseRows={[
          {
            value: 'Suspended',
            label: t('list.statusTip.suspended.label'),
            detail: t('list.statusTip.suspended.detail'),
          },
          {
            value: 'Created',
            label: t('list.statusTip.created.label'),
            detail: t('list.statusTip.created.detail'),
          },
          {
            value: 'PodsRunning',
            label: t('list.statusTip.podsRunning.label'),
            detail: t('list.statusTip.podsRunning.detail'),
          },
          {
            value: 'Running',
            label: phaseLabel('Running'),
            detail: t('list.statusTip.running.detail'),
          },
          {
            value: 'Faulted',
            label: t('list.statusTip.faulted.label'),
            detail: t('list.statusTip.faulted.detail'),
          },
          {
            value: 'Completed',
            label: phaseLabel('Completed'),
            detail: t('list.statusTip.completed.detail'),
          },
          {
            value: 'Failed',
            label: phaseLabel('Failed'),
            detail: t('list.statusTip.failed.detail'),
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
                  onChange: (v: string) => setScope(v as TrainingScope),
                  options: [
                    { value: 'all', label: t('list.scope.all'), count: allRows.length },
                    {
                      value: 'mine',
                      label: t('list.scope.mine'),
                      // 后端 scope=mine 集 (含分享给我的), 非 creator===me
                      count: allRows.filter((r) => mineIds.has(r.id)).length,
                    },
                  ],
                },
              ]
            : []),
        ]}
      />
      <ProTable<TrainingJobListItem>
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
        scroll={{ x: 1100 }}
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
        title={t('list.statusDetailTitle')}
        detailId={detailId}
        fetcher={getTrainingStatusDetail}
        onClose={() => setDetailId(null)}
      />
    </PageContainer>
  );
}
