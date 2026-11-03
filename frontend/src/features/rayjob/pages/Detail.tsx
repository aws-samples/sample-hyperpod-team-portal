import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
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
  Typography,
  message,
} from 'antd';
import {
  CopyOutlined,
  DeleteOutlined,
  PoweroffOutlined,
  ReloadOutlined,
  ShareAltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  deleteRayJob,
  getRayJob,
  getRayJobKueueDetail,
  getRayJobStatusDetail,
  stopRayJob,
} from '../api/client';
import { barePhase, rayPhaseBadge, RAY_TERMINAL_PHASES } from '../api/types';
import type {
  RayJobContainerSummary,
  RayJobDetail,
  RayJobPodSummary,
} from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import ConditionsTimeline from '@/shared/ui/ConditionsTimeline';
import CrPhaseField from '@/shared/ui/CrPhaseField';
import KueueStatusField from '@/shared/ui/KueueStatusField';
import StatusDetailDrawer from '@/shared/ui/StatusDetailDrawer';
import KueueDetailDrawer from '@/shared/components/KueueDetailDrawer';
import RayJobTerminal from '../components/RayJobTerminal';
import RayJobLogViewer from '../components/RayJobLogViewer';
import RayJobLogsTab from '../components/RayJobLogsTab';
import MonitoringTabPanel from '@/shared/ui/metrics/MonitoringTabPanel';
import { listRayjobTemplates } from '@/api/monitoring';
import ShareModal from '@/features/sharing/ShareModal';
import { useAppStore } from '@/store';

const { Text } = Typography;

function podStatusColor(s: string | null | undefined): string {
  const v = (s || '').toLowerCase();
  if (/(crashloop|error|oomkilled|failed|evicted|backoff)/.test(v)) return 'error';
  if (v === 'running') return 'success';
  if (v === 'completed' || v === 'succeeded') return 'blue';
  if (/(pending|containercreating|init|waiting|schedulinggated)/.test(v)) return 'gold';
  return 'default';
}

const TERMINAL = RAY_TERMINAL_PHASES;

export default function RayJobDetailPage() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['rayjob', 'common']);
  const [detail, setDetail] = useState<RayJobDetail | null>(null);
  const [wsName, setWsName] = useState<string>(t('nav.workspace'));
  const [loading, setLoading] = useState(true);
  // pod 终端 Drawer: {pod, container(role→ray-head/ray-worker)}
  const [termPod, setTermPod] = useState<{ pod: string; container: string } | null>(null);
  // pod 实时日志 Drawer: 预选点击的 pod (容器/Driver 双源切换在 RayJobLogViewer 内)
  const [logPod, setLogPod] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('overview');
  const currentUser = useAppStore((s) => s.currentUser);
  // 分享: 仅 creator 本人可见入口 (被分享者不能二次转分享)
  const [shareOpen, setShareOpen] = useState(false);
  // "CR 详情" 抽屉: 只读看原始 status_detail (与训练详情页一致)
  const [crDetailOpen, setCrDetailOpen] = useState(false);
  // "Kueue 详情" 抽屉: 实时查 Workload conditions + admission
  const [kueueOpen, setKueueOpen] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const d = await getRayJob(id, { sync: true });
      setDetail(d);
    } catch (err) {
      message.error(
        t('messages.loadFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!wsId) return;
    getWorkspace(wsId).then((w) => setWsName(w.display_name)).catch(() => undefined);
  }, [wsId]);

  const handleStop = async () => {
    try {
      await stopRayJob(id);
      message.success(t('detail.messages.stopped'));
      load();
    } catch (err) {
      message.error(
        t('messages.stopFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    }
  };

  const handleDelete = async () => {
    try {
      await deleteRayJob(id);
      message.success(t('detail.messages.deleted'));
      navigate(`/workspaces/${wsId}/rayjob`);
    } catch (err) {
      message.error(
        t('messages.deleteFailed', { error: err instanceof Error ? err.message : String(err) }),
      );
    }
  };

  // 毫核区间 → "x.x–y.y 核/cores" (区间两端不同 → 复数; 相等 → 按该值取单复数)
  const coresRange = (reqMilli: number, limMilli: number) =>
    `${(reqMilli / 1000).toFixed(1)}–${(limMilli / 1000).toFixed(1)} ${t('spec.unitCore', {
      count: reqMilli === limMilli ? Number((limMilli / 1000).toFixed(1)) : 2,
    })}`;

  const podColumns: ColumnsType<RayJobPodSummary> = [
    { title: 'Pod', dataIndex: 'name', ellipsis: true },
    {
      title: t('detail.pods.role'),
      dataIndex: 'role',
      width: 90,
      render: (v) => (v ? <Tag color={v === 'head' ? 'purple' : 'geekblue'}>{v}</Tag> : '-'),
    },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      width: 140,
      render: (v) => <Tag color={podStatusColor(v as string)}>{(v as string) || '-'}</Tag>,
    },
    { title: 'Ready', dataIndex: 'ready', width: 80 },
    { title: t('detail.pods.restarts'), dataIndex: 'restarts', width: 90 },
    { title: t('detail.pods.node'), dataIndex: 'node_name', ellipsis: true },
    {
      title: 'Pod IP',
      dataIndex: 'pod_ip',
      width: 130,
      // driver 日志里 (RayTrainWorker ip=x.x.x.x) 的 ip 就对上这里, 方便反查是哪个 pod
      render: (v) => (v ? <Text code>{v as string}</Text> : '-'),
    },
    {
      title: t('common:fields.actions'),
      width: 130,
      // 固定右侧: 表格横向滚动时操作列常驻可见 (与训练详情页一致)
      fixed: 'right',
      render: (_, row) =>
        row.name ? (
          <Space size={12}>
            <a onClick={() => setLogPod(row.name as string)}>{t('detail.pods.logs')}</a>
            <a
              onClick={() =>
                setTermPod({
                  pod: row.name as string,
                  // pod 容器名: head=ray-head / worker=ray-worker (照 cr.py container_name)
                  container: row.role === 'worker' ? 'ray-worker' : 'ray-head',
                })
              }
            >
              {t('detail.pods.terminal')}
            </a>
          </Space>
        ) : null,
    },
  ];

  // 单 pod 多容器展开子表 (head 现在 = ray-head + driver-log-tailer sidecar; 照多机推理)
  const containerColumns: ColumnsType<RayJobContainerSummary> = [
    {
      title: t('detail.containers.container'),
      dataIndex: 'name',
      width: 150,
      render: (name: string) => {
        const role =
          name === 'ray-head'
            ? { text: t('detail.containers.head'), color: 'purple' }
            : name === 'ray-worker'
              ? { text: t('detail.containers.worker'), color: 'geekblue' }
              : name === 'driver-log-tailer'
                ? { text: t('detail.containers.logExporter'), color: 'cyan' }
                : { text: name || t('detail.containers.fallbackName'), color: 'default' };
        return <Tag color={role.color}>{role.text}</Tag>;
      },
    },
    {
      title: t('detail.containers.name'),
      dataIndex: 'name',
      width: 200,
      render: (v: string) => <Text code style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      width: 140,
      render: (v) => <Tag color={podStatusColor(v as string)}>{(v as string) || '-'}</Tag>,
    },
    {
      title: 'Ready',
      dataIndex: 'ready',
      width: 70,
      render: (v) => (v ? <Tag color="success">✓</Tag> : <Tag>✗</Tag>),
    },
    { title: t('detail.containers.restarts'), dataIndex: 'restarts', width: 90 },
    {
      title: t('detail.containers.reason'),
      dataIndex: 'reason',
      ellipsis: true,
      render: (v) => (v ? <Text type="secondary">{v as string}</Text> : '-'),
    },
  ];

  const isTerminal = detail ? TERMINAL.includes(barePhase(detail.phase as string)) : false;

  return (
    <PageContainer
      loading={loading}
      header={{
        title: detail?.display_name || t('detail.title'),
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{wsName}</a> },
            { title: <a onClick={() => navigate(`/workspaces/${wsId}/rayjob`)}>{t('nav.rayjob')}</a> },
            { title: detail?.display_name || id },
          ],
        },
      }}
      extra={[
        <Button key="refresh" icon={<ReloadOutlined />} onClick={load}>
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="clone"
          icon={<CopyOutlined />}
          disabled={!detail}
          onClick={() =>
            navigate(`/workspaces/${wsId}/rayjob/new?cloneFrom=${detail?.id ?? id}`)
          }
        >
          {t('actions.cloneConfig')}
        </Button>,
        // 分享: 仅 creator 本人可见 (被分享者进详情页无此入口)
        detail && detail.creator_user_id === currentUser?.id ? (
          <Button key="share" icon={<ShareAltOutlined />} onClick={() => setShareOpen(true)}>
            {t('actions.share')}
          </Button>
        ) : null,
        ...(!isTerminal
          ? [
              <Popconfirm key="stop" title={t('detail.confirm.stop')} onConfirm={handleStop}>
                <Button icon={<PoweroffOutlined />}>{t('common:actions.stop')}</Button>
              </Popconfirm>,
            ]
          : []),
        <Popconfirm key="del" title={t('detail.confirm.delete')} onConfirm={handleDelete}>
          <Button danger icon={<DeleteOutlined />}>
            {t('common:actions.delete')}
          </Button>
        </Popconfirm>,
      ]}
    >
      <Tabs
        destroyInactiveTabPane
        activeKey={activeTab}
        onChange={setActiveTab}
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
                          status={rayPhaseBadge[barePhase(detail.phase as string)] ?? 'default'}
                          text={(detail.phase as string) || '-'}
                          onShowDetail={() => setCrDetailOpen(true)}
                        />
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.summary.kueueStatus')}>
                        <KueueStatusField
                          status={detail.kueue_status}
                          onShowDetail={() => setKueueOpen(true)}
                        />
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.scale')}>
                        {t('spec.workerCount', { count: detail.worker_replicas })} ×{' '}
                        {t('spec.gpuCount', { count: detail.gpu_per_node })}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('fields.creator')}>
                        {detail.creator_display_name}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.fields.workspace')}>
                        {detail.workspace_display_name}
                      </Descriptions.Item>
                      <Descriptions.Item label="K8s CR">
                        <Text code>{detail.k8s_cr_name}</Text>
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
                        {detail.created_at
                          ? dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')
                          : '-'}
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
                      labelStyle={{ width: 240 }}
                    >
                      {/* ── 机型 ── */}
                      <Descriptions.Item label={t('detail.config.headInstance')}>
                        <Text code>{detail.head_instance_type}</Text> ·{' '}
                        {t('spec.gpuCount', { count: detail.head_gpu })}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.workerInstance')}>
                        <Text code>{detail.worker_instance_type}</Text> ·{' '}
                        {t('spec.gpuCount', { count: detail.gpu_per_node })}
                      </Descriptions.Item>

                      {/* ── 资源 ── */}
                      <Descriptions.Item label={t('detail.config.headResources')}>
                        {coresRange(detail.head_cpu_request_millicores, detail.head_cpu_limit_millicores)} ·{' '}
                        {(detail.head_memory_request_mib / 1024).toFixed(1)}–
                        {(detail.head_memory_limit_mib / 1024).toFixed(1)} GiB · EFA{' '}
                        {detail.head_efa}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.workerResources')}>
                        {t('spec.replicaCount', { count: detail.worker_replicas })} ·{' '}
                        {coresRange(detail.cpu_request_millicores, detail.cpu_limit_millicores)} ·{' '}
                        {(detail.memory_request_mib / 1024).toFixed(1)}–
                        {(detail.memory_limit_mib / 1024).toFixed(1)} GiB · EFA{' '}
                        {detail.efa_per_node}
                      </Descriptions.Item>

                      {/* ── 镜像 ── */}
                      <Descriptions.Item label={t('detail.config.headImage')} span={2}>
                        <Text code copyable>{detail.head_image}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.workerImage')} span={2}>
                        <Text code copyable>{detail.worker_image}</Text>
                      </Descriptions.Item>

                      {/* ── 启动 ── */}
                      <Descriptions.Item label={t('detail.config.entryScript')} span={2}>
                        {detail.entry_script_path ? (
                          <Text code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            {detail.entry_script_path}
                          </Text>
                        ) : (
                          <Text type="secondary">-</Text>
                        )}
                      </Descriptions.Item>

                      {/* ── 共享存储 ── */}
                      <Descriptions.Item label={t('detail.config.fsxMounts')} span={2}>
                        {(detail.extra_fsx_mounts ?? []).length ? (
                          <Space direction="vertical" size={2} style={{ width: '100%' }}>
                            {(detail.extra_fsx_mounts ?? []).map((m, i) => (
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
                        {(detail.s3_datasets ?? []).length ? (
                          <Space direction="vertical" size={2} style={{ width: '100%' }}>
                            {(detail.s3_datasets ?? []).map((s, i) => (
                              <Text key={i}>
                                <Text code>{`s3://${s.bucket}/${s.prefix || ''}`}</Text>
                                <Text type="secondary"> → </Text>
                                <Text code>{s.mount_path}</Text>
                                <Tag style={{ marginLeft: 8 }}>{t('common:storagePicker.readOnly')}</Tag>
                              </Text>
                            ))}
                          </Space>
                        ) : (
                          <Text type="secondary">{t('detail.config.none')}</Text>
                        )}
                      </Descriptions.Item>

                      {/* ── 环境 ── */}
                      <Descriptions.Item label={t('detail.config.envVars')} span={2}>
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
                      {(detail.env_secrets ?? []).length ? (
                        <Descriptions.Item label={t('detail.config.envSecrets')} span={2}>
                          <Space wrap>
                            {(detail.env_secrets ?? []).map((s, i) => (
                              <Tag key={i}>
                                {s.name} ← {s.secret_ref || t('detail.config.ownSecret')}:{s.secret_key}
                              </Tag>
                            ))}
                          </Space>
                        </Descriptions.Item>
                      ) : null}

                      {/* ── 运行策略 ── */}
                      <Descriptions.Item label={t('detail.config.maxRun')}>
                        {t('spec.hourCount', { count: detail.max_run_hours })}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.ttl')}>
                        {detail.ttl_seconds_after_finished}s
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.retries')}>
                        {detail.backoff_limit}
                      </Descriptions.Item>
                      <Descriptions.Item label={t('detail.config.runAs')}>
                        {detail.run_as_root ? 'root' : t('detail.config.nonRoot')}
                      </Descriptions.Item>
                      {detail.labels && Object.keys(detail.labels).length ? (
                        <Descriptions.Item label="Labels" span={2}>
                          <Space wrap>
                            {Object.entries(detail.labels).map(([k, v]) => (
                              <Tag key={k}>{k}={v}</Tag>
                            ))}
                          </Space>
                        </Descriptions.Item>
                      ) : null}
                      {detail.description ? (
                        <Descriptions.Item label={t('common:fields.description')} span={2}>
                          {detail.description}
                        </Descriptions.Item>
                      ) : null}
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
                  <Table
                    rowKey="name"
                    size="small"
                    columns={podColumns}
                    dataSource={detail?.pods || []}
                    pagination={false}
                    scroll={{ x: 'max-content' }}
                    locale={{ emptyText: t('detail.pods.empty') }}
                    expandable={{
                      // 单 pod 有多个容器时才可展开列容器 (head = ray-head + sidecar)
                      rowExpandable: (r) => (r.containers?.length ?? 0) > 1,
                      expandedRowRender: (r) => (
                        <Table<RayJobContainerSummary>
                          rowKey="name"
                          size="small"
                          columns={containerColumns}
                          dataSource={r.containers ?? []}
                          pagination={false}
                        />
                      ),
                    }}
                  />
                </ProCard>

                <ProCard
                  title={t('detail.timeline')}
                  bordered
                  style={{ marginTop: 16 }}
                  collapsible
                  defaultCollapsed={detail?.conditions?.length ? false : true}
                >
                  <ConditionsTimeline conditions={detail?.conditions || []} />
                </ProCard>
              </>
            ),
          },
          {
            key: 'monitoring',
            label: t('detail.tabs.monitoring'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listRayjobTemplates(id);
                  return all.filter((tpl) => tpl.category !== 'ray');
                }}
                depKey={`${id}-metrics`}
                height={220}
                showDimensionSwitch
                banner={
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message={t('detail.monitoringBanner')}
                  />
                }
              />
            ),
          },
          {
            key: 'ray-engine',
            label: t('detail.tabs.rayEngine'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listRayjobTemplates(id);
                  return all.filter((tpl) => tpl.category === 'ray');
                }}
                depKey={`${id}-ray-engine`}
                height={220}
                banner={
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message={t('detail.rayEngineBanner')}
                  />
                }
              />
            ),
          },
          {
            key: 'logs',
            label: t('detail.tabs.logs'),
            children: detail ? <RayJobLogsTab rayjobId={id} /> : null,
          },
        ]}
      />

      <Drawer
        title={t('detail.terminalTitle', {
          pod: termPod?.pod ?? '',
          container: termPod?.container ?? '',
        })}
        width={900}
        open={termPod !== null}
        onClose={() => setTermPod(null)}
        destroyOnClose
        styles={{ body: { padding: 8, background: '#1e1e1e' } }}
      >
        {termPod ? (
          <RayJobTerminal rayjobId={id} pod={termPod.pod} container={termPod.container} />
        ) : null}
      </Drawer>

      <Drawer
        title={t('detail.logsTitle', { pod: logPod ?? '' })}
        width={900}
        open={logPod !== null}
        onClose={() => setLogPod(null)}
        destroyOnClose
      >
        {logPod && detail ? (
          <RayJobLogViewer rayjobId={id} pods={detail.pods ?? []} initialPod={logPod} />
        ) : null}
      </Drawer>

      <StatusDetailDrawer
        open={crDetailOpen}
        title={t('list.statusDetailTitle')}
        detailId={crDetailOpen ? id : null}
        fetcher={getRayJobStatusDetail}
        onClose={() => setCrDetailOpen(false)}
      />

      <KueueDetailDrawer
        open={kueueOpen}
        onClose={() => setKueueOpen(false)}
        fetcher={() => getRayJobKueueDetail(id)}
      />

      {detail ? (
        <ShareModal
          wsId={wsId}
          resType="rayjob"
          resId={detail.id}
          open={shareOpen}
          onClose={() => setShareOpen(false)}
        />
      ) : null}
    </PageContainer>
  );
}
