import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  Alert,
  Badge,
  Button,
  Descriptions,
  Popconfirm,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CopyOutlined,
  DeleteOutlined,
  PoweroffOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  deleteInference,
  getInference,
  getInferenceKueueDetailByWorkload,
  getInferenceStatusDetail,
  stopInference,
} from '../api/client';
import KueueDetailDrawer from '@/shared/components/KueueDetailDrawer';
import type {
  InferenceContainerSummary,
  InferenceDetail,
  InferencePodSummary,
} from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import MonitoringTabPanel from '@/shared/ui/metrics/MonitoringTabPanel';
import { listInferenceTemplates } from '@/api/monitoring';
import InferenceLogsTab from '../components/InferenceLogsTab';
import InvokeSnippets from '../components/InvokeSnippets';
import ConditionsTimeline from '@/shared/ui/ConditionsTimeline';
import { kueueStatusColor, kueueStatusLabel } from '@/shared/status';
import CrPhaseField from '@/shared/ui/CrPhaseField';
import StatusDetailDrawer from '@/shared/ui/StatusDetailDrawer';

const { Text, Paragraph } = Typography;

// pod STATUS → Tag 色: 崩溃/错误红, 运行绿, 完成蓝, 等待橙。
function podStatusColor(s: string | null | undefined): string {
  const v = (s || '').toLowerCase();
  if (/(crashloop|error|oomkilled|failed|evicted|backoff)/.test(v)) return 'error';
  if (v === 'running') return 'success';
  if (v === 'completed' || v === 'succeeded') return 'blue';
  if (/(pending|containercreating|init|waiting)/.test(v)) return 'gold';
  return 'default';
}

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

const sourceLabel: Record<string, string> = {
  fsx: 'FSx Lustre',
  s3: 'S3',
  huggingface: 'HuggingFace Hub',
};

export default function InferenceDetailPage() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['inference', 'common']);
  const [detail, setDetail] = useState<InferenceDetail | null>(null);
  const [wsName, setWsName] = useState<string>(t('nav.workspace'));
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // "Kueue 详情" 抽屉: 按副本 (pod 级 Workload 名) 打开, 实时查该副本 conditions + admission
  const [kueueWl, setKueueWl] = useState<string | null>(null);
  // "CR 详情" 弹窗: 只读看原始 CR status_detail (同列表页放大镜 icon)
  const [crDetailOpen, setCrDetailOpen] = useState(false);

  // silent: 后台轮询不触发全屏 loading (否则每 30s 整页转圈)
  const fetchDetail = useCallback(
    // retryOnFail: 失败时先静默重试一次再报错 (吞掉首屏偶发抖动: 后端冷启动/
    // token 刷新瞬间 401/网络抖动 —— 重试即好, 不该弹红条吓用户)。
    async (sync = false, silent = false, retryOnFail = false) => {
      if (!id) return;
      if (!silent) setLoading(true);
      try {
        const [d, ws] = await Promise.all([
          getInference(id, { sync }),
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
              getInference(id, { sync }),
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
        if (!silent) setLoading(false);
      }
    },
    [id, wsId],
  );

  useEffect(() => {
    // 初次进详情即 sync, 实时拉 conditions/pods (状态时间线/Pod 表)。
    // retryOnFail=true: 首屏偶发失败先静默重试一次, 避免红条一闪。
    void fetchDetail(true, false, true);
  }, [fetchDetail]);

  // 依赖取 phase 而非 detail: 每次 sync 返回新 detail 引用会让 interval 反复重建
  const phase = detail?.phase as string | undefined;
  useEffect(() => {
    if (!phase) return;
    const TERMINAL = ['DeploymentComplete', 'DeploymentFailed', 'Stopped', 'Deleted'];
    if (TERMINAL.includes(phase)) return;
    const timer = setInterval(() => {
      void fetchDetail(true, true);
    }, 30_000);
    return () => clearInterval(timer);
  }, [phase, fetchDetail]);

  const handleDelete = useCallback(async () => {
    if (!id) return;
    try {
      await deleteInference(id);
      message.success(t('messages.deleted'));
      navigate(`/workspaces/${wsId}/inference`);
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      message.error(t('messages.deleteFailed', { error: m }));
    }
  }, [id, wsId, navigate, t]);

  const handleStop = useCallback(async () => {
    if (!id) return;
    try {
      await stopInference(id);
      message.success(t('messages.stopped'));
      await fetchDetail(false);
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      message.error(t('messages.stopFailed', { error: m }));
    }
  }, [id, fetchDetail, t]);

  // 毫核 request / limit → "x.x / y.y 核/cores" (区间形式, 英文恒用复数)
  const coresPair = (reqMilli: number, limMilli: number) =>
    `${(reqMilli / 1000).toFixed(1)} / ${(limMilli / 1000).toFixed(1)} ${t('spec.unitCore', {
      count: 2,
    })}`;

  // pod 展开子表: 一 pod 含主 sglang + reverse-proxy + otel-collector, 各自状态
  const containerColumns: ColumnsType<InferenceContainerSummary> = [
    {
      title: t('detail.containers.role'),
      dataIndex: 'name',
      key: 'role',
      width: 160,
      render: (name: string) => {
        // sidecar 名固定, 主容器名 = 推理 CR name (动态)
        const role =
          name === 'sidecar-reverse-proxy'
            ? { text: t('detail.containers.roles.proxy'), color: 'geekblue' }
            : name === 'otel-collector'
              ? { text: t('detail.containers.roles.metrics'), color: 'cyan' }
              : { text: t('detail.containers.roles.engine'), color: 'purple' };
        return <Tag color={role.color}>{role.text}</Tag>;
      },
    },
    {
      title: t('detail.containers.name'),
      dataIndex: 'name',
      key: 'name',
      width: 240,
      render: (v: string) => (
        <Text copyable style={{ fontSize: 12 }}>
          {v}
        </Text>
      ),
    },
    {
      title: 'Ready',
      dataIndex: 'ready',
      key: 'ready',
      width: 90,
      render: (v: boolean) => (v ? (
          <Tag color="success">{t('detail.containers.ready')}</Tag>
        ) : (
          <Tag>{t('detail.containers.notReady')}</Tag>
        )),
    },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      key: 'status',
      width: 160,
      render: (v: string) => <Tag color={podStatusColor(v)}>{v ?? '-'}</Tag>,
    },
    {
      title: t('detail.pods.restarts'),
      dataIndex: 'restarts',
      key: 'restarts',
      // 英文列头 "Restarts" 更长: 60 → 90
      width: 90,
      render: (v) => v ?? 0,
    },
    {
      title: t('detail.pods.reason'),
      dataIndex: 'reason',
      key: 'reason',
      width: 200,
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
  ];

  const podColumns: ColumnsType<InferencePodSummary> = [
    { title: 'Pod', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: 'Ready', dataIndex: 'ready', key: 'ready', width: 70, render: (v) => v ?? '-' },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      key: 'status',
      width: 160,
      render: (v: string, row) => (
        <Tag color={podStatusColor(v)}>{v ?? row.phase ?? '-'}</Tag>
      ),
    },
    {
      title: t('detail.pods.restarts'),
      dataIndex: 'restarts',
      key: 'restarts',
      // 英文列头 "Restarts" 更长: 60 → 90
      width: 90,
      render: (v) => v ?? 0,
    },
    {
      title: t('detail.pods.reason'),
      dataIndex: 'reason',
      key: 'reason',
      width: 200,
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
    { title: 'Node', dataIndex: 'node_name', key: 'node_name', ellipsis: true },
    { title: 'Pod IP', dataIndex: 'pod_ip', key: 'pod_ip', width: 140 },
    {
      title: 'Start',
      dataIndex: 'start_time',
      key: 'start_time',
      width: 160,
      render: (v: string) => (v ? dayjs(v).format('MM-DD HH:mm:ss') : '-'),
    },
  ];

  // 推理: 每 pod = 一个副本 = 一个 pod 级 Workload。按 workload_name 分组 (缺失回退 pod 名),
  // 每副本一张卡片, 卡头挂该副本自己的 Workload 链接 (点开查该副本 conditions)。
  const podReplicas = useMemo(() => {
    const groups = new Map<string, InferencePodSummary[]>();
    for (const p of detail?.pods ?? []) {
      const key = p.workload_name ?? p.name ?? '';
      const arr = groups.get(key) ?? [];
      arr.push(p);
      groups.set(key, arr);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [detail?.pods]);

  if (err) {
    return (
      <PageContainer>
        <Alert
          type="error"
          message={t('common:messages.loadFailed')}
          description={err}
          showIcon
        />
      </PageContainer>
    );
  }

  if (!detail) {
    return <PageContainer loading={loading} />;
  }

  // 状态直接显原始 CR phase (debug 友好, 与训练/开发机一致); 颜色取 phaseBadge 命中色, 未命中 default
  const meta = {
    status: phaseBadge[detail.phase as string]?.status ?? ('default' as const),
    text: (detail.phase as string) || '-',
  };

  return (
    <PageContainer
      loading={loading}
      header={{
        title: detail.display_name || detail.name,
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>{wsName}</a>
              ),
            },
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}/inference`)}>
                  {t('nav.inference')}
                </a>
              ),
            },
            { title: detail.name },
          ],
        },
      }}
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void fetchDetail(true)}
        >
          {t('detail.forceRefresh')}
        </Button>,
        <Button
          key="clone"
          icon={<CopyOutlined />}
          disabled={!detail}
          onClick={() =>
            navigate(
              `/workspaces/${wsId}/inference/new?cloneFrom=${detail?.id ?? id}`,
            )
          }
        >
          {t('actions.cloneConfig')}
        </Button>,
        ...(!['DeploymentFailed', 'Stopped', 'Deleted'].includes(detail.phase as string)
          ? [
              <Popconfirm
                key="stop"
                title={t('confirm.stopTitle')}
                description={t('confirm.stopDesc')}
                onConfirm={handleStop}
                okText={t('common:actions.stop')}
                cancelText={t('common:actions.cancel')}
              >
                <Button icon={<PoweroffOutlined />}>{t('common:actions.stop')}</Button>
              </Popconfirm>,
            ]
          : []),
        <Popconfirm
          key="delete"
          title={t('confirm.deleteTitle')}
          description={t('confirm.deleteDescDetail')}
          onConfirm={handleDelete}
          okText={t('common:actions.delete')}
          cancelText={t('common:actions.cancel')}
        >
          <Button icon={<DeleteOutlined />} danger>
            {t('common:actions.delete')}
          </Button>
        </Popconfirm>,
      ]}
    >
      <Tabs
        defaultActiveKey="overview"
        items={[
          {
            key: 'overview',
            label: t('detail.tabs.overview'),
            children: (
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                {/* 顶部状态摘要: 3 列横排, 与训练/开发机详情对齐 (状态/规格/标识/时间) */}
                <ProCard bordered>
                  <Descriptions column={3} size="small">
                    <Descriptions.Item label={t('detail.summary.crStatus')}>
                      <CrPhaseField
                        status={meta.status}
                        text={meta.text}
                        onShowDetail={() => setCrDetailOpen(true)}
                      />
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.summary.kueueStatus')}>
                      {kueueStatusLabel(detail.kueue_status) ? (
                        <Badge
                          status={kueueStatusColor(detail.kueue_status)}
                          text={kueueStatusLabel(detail.kueue_status)}
                        />
                      ) : (
                        '-'
                      )}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('fields.spec')}>
                      {detail.replicas} × {t('spec.gpuCount', { count: detail.gpu_per_replica })} ·{' '}
                      {detail.instance_type}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('fields.framework')}>
                      <Tag color="purple">{(detail.framework as string).toUpperCase()}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('fields.creator')}>
                      {detail.creator_display_name}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('fields.workspace')}>
                      {detail.workspace_display_name}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.fields.lastSync')}>
                      {detail.last_sync_at
                        ? dayjs(detail.last_sync_at).format('YYYY-MM-DD HH:mm:ss')
                        : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="K8s Namespace">
                      <Text code>{detail.k8s_namespace}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="CR Name">
                      <Text code>{detail.k8s_endpoint_name}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('common:fields.createdAt')}>
                      {dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
                    </Descriptions.Item>
                  </Descriptions>
                </ProCard>

                {/* 运行配置: 统一一个 Descriptions, label 宽度一致 */}
                <ProCard title={t('detail.config.title')} bordered collapsible defaultCollapsed={false}>
                  <Descriptions
                    column={2}
                    size="small"
                    bordered
                    // 英文 label (Memory (request / limit)) 更长: 200 → 240
                    labelStyle={{ width: 240 }}
                  >
                    {/* ── 镜像 ── */}
                    <Descriptions.Item label={t('fields.image')} span={2}>
                      <Text code copyable>{detail.image}</Text>
                    </Descriptions.Item>

                    {/* ── 模型来源 ── */}
                    <Descriptions.Item label={t('detail.config.modelSource')}>
                      <Tag>{sourceLabel[detail.model_source_type] ?? detail.model_source_type}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.sharedMount')}>
                      {detail.model_source_type === 'fsx' && detail.fsx ? (
                        <Text code>{detail.fsx.mount_name || detail.fsx.filesystem_id}</Text>
                      ) : detail.model_source_type === 's3' && detail.s3 ? (
                        <Text>
                          <Text code>{detail.s3.bucket_name}</Text>
                          <Text type="secondary"> / {detail.s3.model_location}</Text>
                        </Text>
                      ) : detail.model_source_type === 'huggingface' && detail.huggingface ? (
                        <Text code>{detail.huggingface.model_id}</Text>
                      ) : (
                        <Text type="secondary">-</Text>
                      )}
                    </Descriptions.Item>

                    {/* ── 计算资源 ── */}
                    <Descriptions.Item label={t('detail.config.instanceType')}>
                      <Text code>{detail.instance_type}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.replicas')}>
                      {detail.replicas}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.gpuPerReplica')}>
                      {detail.gpu_per_replica}{' '}
                      {t('spec.unitCard', { count: detail.gpu_per_replica })}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.containerPort')}>
                      {detail.container_port}
                    </Descriptions.Item>
                    <Descriptions.Item label="CPU (request / limit)">
                      {coresPair(detail.cpu_request_millicores, detail.cpu_limit_millicores)}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.memory')}>
                      {(detail.memory_request_mib / 1024).toFixed(1)} / {(detail.memory_limit_mib / 1024).toFixed(1)} GiB
                    </Descriptions.Item>

                    {/* ── 启动配置 ── */}
                    <Descriptions.Item label={t('detail.config.launchScript')} span={2}>
                      {detail.launch_script ? (
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
                          {detail.launch_script}
                        </pre>
                      ) : detail.sglang_extra_args.length > 0 ? (
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
                          {detail.sglang_extra_args.join(' ')}
                        </pre>
                      ) : (
                        <Text type="secondary">{t('detail.config.defaultLaunch')}</Text>
                      )}
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.metricsEnabled')}>
                      <Tag color={detail.metrics_enabled ? 'green' : 'default'}>
                        {detail.metrics_enabled
                          ? t('detail.config.enabled')
                          : t('detail.config.disabled')}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label={t('detail.config.publicEndpoint')}>
                      <Tag color={detail.public_endpoint ? 'green' : 'default'}>
                        {detail.public_endpoint
                          ? t('detail.config.enabled')
                          : t('detail.config.disabled')}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="Labels" span={2}>
                      {detail.labels && Object.keys(detail.labels).length ? (
                        <Space wrap style={{ maxWidth: '100%' }}>
                          {Object.entries(detail.labels).map(([k, v]) => (
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

                    {/* ── 描述 ── */}
                    {detail.description && (
                      <Descriptions.Item label={t('common:fields.description')} span={2}>
                        {detail.description}
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </ProCard>

                {/* Pods 独占一行, 按副本分卡片 (每副本一个 pod 级 Workload) */}
                <ProCard
                  title={t('detail.pods.title', { total: detail.pods.length })}
                  bordered
                  collapsible
                  defaultCollapsed={false}
                >
                  {podReplicas.length === 0 ? (
                    <Typography.Text type="secondary">
                      {t('detail.pods.empty')}
                    </Typography.Text>
                  ) : (
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      {podReplicas.map(([key, replicaPods]) => {
                        const wlName =
                          replicaPods.find((p) => p.workload_name)?.workload_name ?? null;
                        return (
                          <ProCard
                            key={key}
                            type="inner"
                            bordered
                            title={
                              <Space>
                                <span>{t('detail.pods.replica')}</span>
                                {wlName ? (
                                  <a
                                    onClick={() => setKueueWl(wlName)}
                                    style={{ fontWeight: 'normal', fontSize: 12 }}
                                  >
                                    Workload: {wlName}
                                  </a>
                                ) : null}
                              </Space>
                            }
                          >
                            <Table<InferencePodSummary>
                              rowKey={(r, idx) => r.name ?? `${idx}`}
                              columns={podColumns}
                              dataSource={replicaPods}
                              pagination={false}
                              size="small"
                              scroll={{ x: 'max-content' }}
                              expandable={{
                                expandedRowRender: (r) => (
                                  <Table<InferenceContainerSummary>
                                    rowKey={(c, i) => c.name ?? `${i}`}
                                    columns={containerColumns}
                                    dataSource={r.containers ?? []}
                                    pagination={false}
                                    size="small"
                                    scroll={{ x: 'max-content' }}
                                    locale={{ emptyText: t('detail.containers.empty') }}
                                  />
                                ),
                                rowExpandable: (r) => !!r.containers?.length,
                              }}
                            />
                          </ProCard>
                        );
                      })}
                    </Space>
                  )}
                </ProCard>

                {/* 状态时间线 · 放到「当前运行的 Pods」下面 */}
                <ProCard
                  title={t('detail.timeline')}
                  bordered
                >
                  <ConditionsTimeline conditions={detail.conditions} />
                </ProCard>

                {detail.sglang_extra_args.length > 0 && (
                  <ProCard title={t('detail.sglangArgs')} bordered>
                    <Paragraph copyable style={{ fontFamily: 'monospace' }}>
                      {detail.sglang_extra_args.join(' ')}
                    </Paragraph>
                  </ProCard>
                )}

                <InvokeSnippets detail={detail} />
              </Space>
            ),
          },
          {
            key: 'metrics',
            label: t('detail.tabs.monitoring'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listInferenceTemplates(detail.id);
                  return all.filter((tpl) => tpl.category !== 'sglang');
                }}
                depKey={`${detail.id}-metrics`}
                height={220}
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
            key: 'sglang',
            label: t('detail.tabs.sglang'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listInferenceTemplates(detail.id);
                  return all.filter((tpl) => tpl.category === 'sglang');
                }}
                depKey={`${detail.id}-sglang`}
                height={220}
                banner={
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message={t('detail.sglangBanner')}
                  />
                }
              />
            ),
          },
          {
            key: 'logs',
            label: t('detail.tabs.logs'),
            // 统一走 CloudWatch 历史组件 (不分运行中/终态, 对齐训练)。运行中任务
            // 下滑追更新 (~30s CW 采集延迟可接受)。旧实时 LogViewer/SSE 暂保留不删。
            children: <InferenceLogsTab inferenceId={detail.id} />,
          },
        ]}
      />

      <KueueDetailDrawer
        // key=workload 名: 切换到另一副本的 workload 链接时强制 remount 重新 fetch。
        key={kueueWl ?? 'closed'}
        open={kueueWl != null}
        onClose={() => setKueueWl(null)}
        fetcher={() => getInferenceKueueDetailByWorkload(id, kueueWl as string)}
      />

      <StatusDetailDrawer
        open={crDetailOpen}
        title={t('statusDetailTitle')}
        detailId={crDetailOpen ? id : null}
        fetcher={getInferenceStatusDetail}
        onClose={() => setCrDetailOpen(false)}
      />
    </PageContainer>
  );
}
