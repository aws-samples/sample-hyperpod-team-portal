import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import yaml from 'js-yaml';
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import LogViewer from '../components/LogViewer';
import PodTerminal from '../components/PodTerminal';
import TrainingLogsTab from '../components/TrainingLogsTab';
import MetricsCharts from '../components/MetricsCharts';
import type { ColumnsType } from 'antd/es/table';
import {
  CopyOutlined,
  DeleteOutlined,
  PoweroffOutlined,
  ReloadOutlined,
  ShareAltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  deleteTrainingJob,
  getTrainingJob,
  getTrainingKueueDetail,
  getTrainingStatusDetail,
  stopTrainingJob,
} from '../api/client';
import type { TrainingJobDetail, TrainingPodSummary } from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import { phaseColor } from '@/shared/status';
import KueueDetailDrawer from '@/shared/components/KueueDetailDrawer';
import ConditionsTimeline from '@/shared/ui/ConditionsTimeline';
import KueueStatusField from '@/shared/ui/KueueStatusField';
import CrPhaseField from '@/shared/ui/CrPhaseField';
import StatusDetailDrawer from '@/shared/ui/StatusDetailDrawer';
import PriorityTag from '@/shared/ui/PriorityTag';
import ShareModal from '@/features/sharing/ShareModal';
import { useAppStore } from '@/store';

const { Text } = Typography;

// pod STATUS → Tag 色。崩溃/错误类红, 运行类绿, 完成蓝, 等待类橙。
function podStatusColor(s: string | null | undefined): string {
  const v = (s || '').toLowerCase();
  if (/(crashloop|error|oomkilled|failed|evicted|backoff)/.test(v)) return 'error';
  if (v === 'running') return 'success';
  if (v === 'completed' || v === 'succeeded') return 'blue';
  if (/(pending|containercreating|init|waiting)/.test(v)) return 'gold';
  return 'default';
}

export default function TrainingDetail() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['training', 'common']);
  const [detail, setDetail] = useState<TrainingJobDetail | null>(null);
  const [wsName, setWsName] = useState<string>(t('nav.workspace'));
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // pod 表"日志"按钮: 打开 Drawer 看该 pod 实时日志
  const [logPod, setLogPod] = useState<string | null>(null);
  // Tabs 受控 activeKey (支持从实时日志抽屉"跳转到日志页"切 tab)
  const [activeTab, setActiveTab] = useState('overview');
  // "跳转到日志页"预选的 pod (历史日志组件按此选该 pod 最后一个 stream)
  const [logInitialPod, setLogInitialPod] = useState<string | undefined>();
  // pod 表"终端"按钮: 打开 Drawer 进 pod 交互终端
  const [termPod, setTermPod] = useState<string | null>(null);
  // "Kueue 详情" 抽屉: 实时查 Workload conditions + admission
  const [kueueOpen, setKueueOpen] = useState(false);
  // "CR 详情" 弹窗: 只读看原始 CR status_detail (同列表页放大镜 icon)
  const [crDetailOpen, setCrDetailOpen] = useState(false);
  // 分享弹窗 (仅 creator 本人可见入口)
  const [shareOpen, setShareOpen] = useState(false);
  const currentUser = useAppStore((s) => s.currentUser);

  const fetchDetail = useCallback(
    // retryOnFail: 失败时先静默重试一次再报错 (吞掉首屏偶发抖动: 后端冷启动/
    // token 刷新瞬间 401/网络抖动 —— 重试即好, 不该弹红条吓用户)。
    async (sync = false, retryOnFail = false) => {
      if (!id) return;
      setLoading(true);
      try {
        const [d, ws] = await Promise.all([
          getTrainingJob(id, { sync }),
          getWorkspace(wsId).catch(() => null),
        ]);
        setDetail(d);
        if (ws) setWsName(ws.display_name);
        setErr(null);
      } catch (e) {
        if (retryOnFail) {
          // 静默重试一次 (隔 800ms); 成功则无感, 仍失败才真正报错。
          await new Promise((r) => setTimeout(r, 800));
          try {
            const [d, ws] = await Promise.all([
              getTrainingJob(id, { sync }),
              getWorkspace(wsId).catch(() => null),
            ]);
            setDetail(d);
            if (ws) setWsName(ws.display_name);
            setErr(null);
            return;
          } catch (e2) {
            setErr((e2 as Error).message);
            return;
          }
        }
        setErr((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [id, wsId],
  );

  // 与列表页同一入口 (POST /stop)。停完重读 DDB 拿 phase=Stopped, 按钮随之消失。
  const handleStop = useCallback(async () => {
    try {
      await stopTrainingJob(detail?.id ?? id);
      message.success(t('messages.stopped'));
      await fetchDetail(false);
    } catch (e) {
      message.error(
        t('messages.stopFailed', { error: e instanceof Error ? e.message : String(e) }),
      );
    }
  }, [detail?.id, id, fetchDetail, t]);

  // 首次进详情默从 DDB 读 (秒响应), 不 sync K8s — 产品要求.
  // retryOnFail=true: 首屏偶发失败先静默重试一次, 避免红条一闪。
  useEffect(() => {
    void fetchDetail(false, true);
  }, [fetchDetail]);

  // 非终态时, 30s 后台静默 sync 一次拉真实状态
  // (旧版 8s 太频繁 + 走 sync 慢)
  useEffect(() => {
    if (!detail) return;
    // 非终态 (未含 Complete/Failed) 时 30s 后台静默 sync 一次拉真实状态
    const phase = detail.phase || '';
    if (phase.includes('Complete') || phase.includes('Failed')) return;
    const timer = setInterval(() => void fetchDetail(true), 30_000);
    return () => clearInterval(timer);
  }, [detail, fetchDetail]);

  // 毫核 → "x.x 核/cores" (英文按数量取单复数)
  const coresText = (millicores: number) =>
    `${(millicores / 1000).toFixed(1)} ${t('spec.unitCore', {
      count: Number((millicores / 1000).toFixed(1)),
    })}`;

  const podColumns: ColumnsType<TrainingPodSummary> = [
    { title: 'Pod', dataIndex: 'name', key: 'name' },
    { title: 'Ready', dataIndex: 'ready', key: 'ready', width: 70, render: (v) => v ?? '-' },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      key: 'status',
      width: 150,
      render: (v, row) => <Tag color={podStatusColor(v)}>{v ?? row.phase ?? '-'}</Tag>,
    },
    {
      title: t('detail.pods.restarts'),
      dataIndex: 'restarts',
      key: 'restarts',
      // 英文 "Restarts" 比中文长, 70 → 96
      width: 96,
      render: (v) => v ?? 0,
    },
    {
      title: t('detail.pods.reason'),
      dataIndex: 'reason',
      key: 'reason',
      width: 220,
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="danger" style={{ fontSize: 12 }}>
              {v}
            </Text>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    { title: t('detail.pods.node'), dataIndex: 'node_name', key: 'node_name', ellipsis: true },
    { title: 'Pod IP', dataIndex: 'pod_ip', key: 'pod_ip', width: 140 },
    {
      title: t('common:fields.actions'),
      key: 'action',
      width: 150,
      fixed: 'right',
      render: (_, row) => (
        <Space size={0}>
          <Button size="small" type="link" onClick={() => setLogPod(row.name)}>
            {t('detail.pods.logs')}
          </Button>
          <Button size="small" type="link" onClick={() => setTermPod(row.name)}>
            {t('detail.pods.terminal')}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer
      header={{
        title: detail?.display_name || detail?.name || t('detail.title'),
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>{wsName}</a>
              ),
            },
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}/training`)}>
                  {t('nav.training')}
                </a>
              ),
            },
            { title: detail?.name || t('detail.crumbLoading') },
          ],
        },
      }}
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          onClick={() => void fetchDetail(true)}
        >
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="clone"
          icon={<CopyOutlined />}
          disabled={!detail}
          onClick={() =>
            navigate(
              `/workspaces/${wsId}/training/new?cloneFrom=${detail?.id ?? id}`,
            )
          }
        >
          {t('actions.cloneConfig')}
        </Button>,
        // 分享: 仅 creator 本人可见 (被分享者进详情页无此入口, 不能二次转分享)
        detail && detail.creator_user_id === currentUser?.id ? (
          <Button
            key="share"
            icon={<ShareAltOutlined />}
            onClick={() => setShareOpen(true)}
          >
            {t('actions.share')}
          </Button>
        ) : null,
        // 仅 creator 本人 + 非终态; 终态词表与 List.tsx 一致 (见那边注释)
        detail &&
        detail.creator_user_id === currentUser?.id &&
        !/Complete|Succeeded|Failed|Stopped/i.test(detail.phase || '') ? (
          <Popconfirm
            key="stop"
            title={t('confirm.stopTitle')}
            description={t('confirm.stopDesc')}
            okText={t('common:actions.stop')}
            cancelText={t('common:actions.cancel')}
            onConfirm={handleStop}
          >
            <Button icon={<PoweroffOutlined />}>{t('common:actions.stop')}</Button>
          </Popconfirm>
        ) : null,
        detail && detail.creator_user_id === currentUser?.id ? (
          <Popconfirm
            key="delete"
            title={t('confirm.deleteTitle')}
            description={t('confirm.deleteDescDetail')}
            okType="danger"
            okText={t('common:actions.delete')}
            cancelText={t('common:actions.cancel')}
            onConfirm={async () => {
              try {
                await deleteTrainingJob(detail?.id ?? id);
                message.success(t('messages.deleted'));
                navigate(`/workspaces/${wsId}/training`);
              } catch (e) {
                const m = e instanceof Error ? e.message : String(e);
                message.error(t('messages.deleteFailed', { error: m }));
              }
            }}
          >
            <Button danger icon={<DeleteOutlined />} disabled={!detail}>
              {t('common:actions.delete')}
            </Button>
          </Popconfirm>
        ) : null,
      ]}
    >
      {err && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('messages.loadFailed', { error: err })}
        />
      )}

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        destroyInactiveTabPane
        items={[
          {
            key: 'overview',
            label: t('detail.tabs.overview'),
            children: (
              <>
                <ProCard bordered loading={loading && !detail}>
                  {detail && (
                    <Descriptions column={3} size="small">
                      <Descriptions.Item label={t('detail.summary.crStatus')}>
                        <CrPhaseField
                          status={phaseColor(detail.phase)}
                          text={detail.phase || '-'}
                          onShowDetail={() => setCrDetailOpen(true)}
                        />
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.summary.kueueStatus')}>
                        <KueueStatusField
                          status={detail.kueue_status}
                          onShowDetail={() => setKueueOpen(true)}
                        />
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.spec')}>
                        {detail.node_count}
                        {detail.spares
                          ? t('detail.sparesSuffix', { count: detail.spares })
                          : ''}{' '}
                        × {t('spec.gpuCount', { count: detail.gpu_per_node })} ·{' '}
                        {coresText(detail.cpu_per_node_millicores)} ·{' '}
                        {(detail.memory_per_node_mib / 1024).toFixed(1)} GiB
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.creator')}>
                        {detail.creator_display_name}
                      </Descriptions.Item>
                      <Descriptions.Item label="K8s Job">
                        <Text code>{detail.k8s_job_name}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="Namespace">
                        <Text code>{detail.k8s_namespace}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.fields.lastSync')}>
                        {detail.last_sync_at
                          ? dayjs(detail.last_sync_at).format('YYYY-MM-DD HH:mm:ss')
                          : '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('common:fields.createdAt')}>
                        {dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.fields.startedAt')}>
                        {detail.started_at
                          ? dayjs(detail.started_at).format('YYYY-MM-DD HH:mm:ss')
                          : '-'}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('common:fields.endedAt')}>
                        {detail.ended_at
                          ? dayjs(detail.ended_at).format('YYYY-MM-DD HH:mm:ss')
                          : '-'}
                      </Descriptions.Item>
                    </Descriptions>
                  )}
                </ProCard>

                {detail && (
                  <ProCard
                    title={t('detail.config.title')}
                    bordered
                    style={{ marginTop: 16 }}
                    collapsible
                    defaultCollapsed={false}
                  >
                    <Descriptions
                      column={2}
                      size="small"
                      bordered
                      labelStyle={{ width: 200 }}
                    >
                      {/* ── 镜像 ── */}
                      <Descriptions.Item label={t('fields.image')} span={2}>
                        <Text code copyable>{detail.image}</Text>
                      </Descriptions.Item>

                      {/* ── 计算资源 ── */}
                      <Descriptions.Item label={t('fields.instanceType')}>
                        {detail.instance_type ? <Text code>{detail.instance_type}</Text> : <Text type="secondary">-</Text>}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.nodeCount')}>
                        {detail.node_count}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.spares')}>
                        {detail.spares ? (
                          detail.spares
                        ) : (
                          <Text type="secondary">-</Text>
                        )}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.gpuPerNode')}>
                        {detail.gpu_per_node} {t('spec.unitCard', { count: detail.gpu_per_node })}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.cpuPerNode')}>
                        {coresText(detail.cpu_per_node_millicores)}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.memPerNode')}>
                        {(detail.memory_per_node_mib / 1024).toFixed(1)} GiB
                      </Descriptions.Item>
                      <Descriptions.Item label="EFA">
                        {detail.efa_per_node ?? 0}
                      </Descriptions.Item>
                      {detail.topology_mode && detail.topology_mode !== 'none' && (
                        <>
                          <Descriptions.Item label={t('detail.config.topologyMode')}>
                            <Tag>{detail.topology_mode}</Tag>
                          </Descriptions.Item>
                          <Descriptions.Item label={t('detail.config.topologyLevel')}>
                            <Text code>{detail.topology_label || '-'}</Text>
                          </Descriptions.Item>
                        </>
                      )}

                      {/* ── 共享存储 ── */}
                      <Descriptions.Item label={t('detail.config.fsxMounts')} span={2}>
                        {detail.extra_fsx_mounts && detail.extra_fsx_mounts.length ? (
                          <Space direction="vertical" size={2} style={{ width: '100%' }}>
                            {detail.extra_fsx_mounts.map((m, i) => (
                              <Text key={i}>
                                <Text code>{m.pvc_name}</Text>
                                <Text type="secondary"> → </Text>
                                <Text code>{m.mount_path}</Text>
                                <Tag style={{ marginLeft: 8 }}>
                                  {m.read_only
                                    ? t('common:storagePicker.readOnly')
                                    : t('common:storagePicker.readWrite')}
                                </Tag>
                              </Text>
                            ))}
                          </Space>
                        ) : (
                          <Text type="secondary">{t('detail.config.none')}</Text>
                        )}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.s3Datasets')} span={2}>
                        {detail.s3_datasets && detail.s3_datasets.length ? (
                          <Space direction="vertical" size={2} style={{ width: '100%' }}>
                            {detail.s3_datasets.map((d, i) => (
                              <Text key={i}>
                                <Text code>{`s3://${d.bucket}/${d.prefix || ''}`}</Text>
                                <Text type="secondary"> → </Text>
                                <Text code>{d.mount_path}</Text>
                                {/* S3 挂载全局只读 (mount-s3 read-only) */}
                                <Tag style={{ marginLeft: 8 }}>{t('common:storagePicker.readOnly')}</Tag>
                              </Text>
                            ))}
                          </Space>
                        ) : (
                          <Text type="secondary">{t('detail.config.none')}</Text>
                        )}
                      </Descriptions.Item>

                      {/* ── 启动配置 ── */}
                      <Descriptions.Item label={t('fields.launchCommand')} span={2}>
                        <pre
                          style={{
                            background: '#f5f5f5',
                            padding: 12,
                            borderRadius: 4,
                            fontSize: 12,
                            margin: 0,
                            overflowX: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            userSelect: 'text',
                          }}
                        >
                          {typeof detail.command === 'string'
                            ? detail.command
                            : (detail.command as string[]).join(' ')}
                        </pre>
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.envVars')} span={2}>
                        {Object.keys(detail.env || {}).length ? (
                          <Space wrap style={{ maxWidth: '100%' }}>
                            {Object.entries(detail.env).map(([k, v]) => (
                              <Tag
                                key={k}
                                style={{ whiteSpace: 'normal', wordBreak: 'break-all', maxWidth: '100%' }}
                              >
                                {k}={v}
                              </Tag>
                            ))}
                          </Space>
                        ) : (
                          <Text type="secondary">{t('detail.config.none')}</Text>
                        )}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.priority')} span={2}>
                        <PriorityTag priorityClass={detail.priority_class} />
                      </Descriptions.Item>
                      <Descriptions.Item label="Labels" span={2}>
                        {detail.labels && Object.keys(detail.labels).length ? (
                          <Space wrap>
                            {Object.entries(detail.labels).map(([k, v]) => (
                              <Tag key={k}>{k}={v}</Tag>
                            ))}
                          </Space>
                        ) : (
                          <Text type="secondary">{t('detail.config.none')}</Text>
                        )}
                      </Descriptions.Item>

                      {/* ── 运行策略 ── */}
                      <Descriptions.Item label={t('detail.config.runPolicy')} span={2}>
                        <pre
                          style={{
                            background: '#f5f5f5',
                            padding: 12,
                            borderRadius: 4,
                            fontSize: 12,
                            margin: 0,
                            overflowX: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            userSelect: 'text',
                          }}
                        >
                          {yaml.dump(
                            detail.run_policy_override && Object.keys(detail.run_policy_override).length > 0
                              ? detail.run_policy_override
                              : {
                                  cleanPodPolicy: detail.clean_pod_policy ?? 'All',
                                  jobMaxRetryCount: detail.job_max_retry_count ?? 0,
                                  ttlSecondsAfterFinished: detail.ttl_seconds_after_finished ?? -1,
                                  ...(detail.active_deadline_seconds != null
                                    ? { activeDeadlineSeconds: detail.active_deadline_seconds }
                                    : {}),
                                },
                            { indent: 2, lineWidth: -1 },
                          ).trim()}
                        </pre>
                      </Descriptions.Item>

                      {/* ── 描述 ── */}
                      {detail.description && (
                        <Descriptions.Item label={t('common:fields.description')} span={2}>
                          {detail.description}
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                  </ProCard>
                )}

                <ProCard
                  title={t('detail.pods.title', { total: detail?.pods?.length ?? 0 })}
                  bordered
                  style={{ marginTop: 16 }}
                  collapsible
                  defaultCollapsed={false}
                >
                  <Table<TrainingPodSummary>
                    size="small"
                    columns={podColumns}
                    dataSource={detail?.pods ?? []}
                    rowKey="name"
                    pagination={false}
                    scroll={{ x: 'max-content' }}
                    locale={{ emptyText: t('detail.pods.empty') }}
                  />
                </ProCard>

                <Drawer
                  title={t('detail.liveLogsTitle', { pod: logPod ?? '' })}
                  width={900}
                  open={!!logPod}
                  onClose={() => setLogPod(null)}
                  destroyOnClose
                  extra={
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => {
                        // 切到日志 tab 并预选该 pod (历史组件选其最后一个 stream)
                        setLogInitialPod(logPod ?? undefined);
                        setLogPod(null);
                        setActiveTab('logs');
                      }}
                    >
                      {t('detail.viewInLogsTab')}
                    </Button>
                  }
                >
                  {logPod && detail && (
                    <LogViewer
                      trainingJobId={detail.id}
                      pods={detail.pods}
                      initialPod={logPod}
                    />
                  )}
                </Drawer>

                <Drawer
                  title={t('detail.terminalTitle', { pod: termPod ?? '' })}
                  width={900}
                  open={!!termPod}
                  onClose={() => setTermPod(null)}
                  destroyOnClose
                  styles={{ body: { background: '#1e1e1e', padding: 8 } }}
                >
                  {termPod && detail && (
                    <PodTerminal trainingJobId={detail.id} pod={termPod} />
                  )}
                </Drawer>

                <KueueDetailDrawer
                  open={kueueOpen}
                  onClose={() => setKueueOpen(false)}
                  fetcher={() => getTrainingKueueDetail(id)}
                />

                <StatusDetailDrawer
                  open={crDetailOpen}
                  title={t('list.statusDetailTitle')}
                  detailId={crDetailOpen ? id : null}
                  fetcher={getTrainingStatusDetail}
                  onClose={() => setCrDetailOpen(false)}
                />

                <ProCard
                  title={t('detail.timeline')}
                  bordered
                  style={{ marginTop: 16 }}
                  collapsible
                  defaultCollapsed={!!detail?.conditions?.length ? false : true}
                >
                  <ConditionsTimeline conditions={detail?.conditions ?? []} />
                </ProCard>
              </>
            ),
          },
          {
            key: 'monitoring',
            label: t('detail.tabs.monitoring'),
            children: detail ? (
              <MetricsCharts trainingJobId={detail.id} height={220} />
            ) : null,
          },
          {
            key: 'logs',
            label: t('detail.tabs.logs'),
            // 统一走 CloudWatch 历史组件 (不分运行中/终态)。运行中任务下滑追更新
            // (~30s CW 采集延迟可接受)。旧实时 LogViewer/SSE 暂保留不删。
            children: detail ? (
              <TrainingLogsTab
                trainingJobId={detail.id}
                initialPod={logInitialPod}
              />
            ) : null,
          },
        ]}
      />
      {detail ? (
        <ShareModal
          wsId={wsId}
          resType="train"
          resId={detail.id}
          open={shareOpen}
          onClose={() => setShareOpen(false)}
        />
      ) : null}
    </PageContainer>
  );
}
