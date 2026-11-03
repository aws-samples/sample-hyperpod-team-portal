import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
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
import { deleteLlmd, getLlmd, getLlmdKueueDetail, stopLlmd } from '../api/client';
import type { LlmdContainerSummary, LlmdDetail, LlmdPodSummary } from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import KueueDetailDrawer from '@/shared/components/KueueDetailDrawer';
import ConditionsTimeline from '@/shared/ui/ConditionsTimeline';
import MonitoringTabPanel from '@/shared/ui/metrics/MonitoringTabPanel';
import { listLlmdTemplates } from '@/api/monitoring';
import LlmdLogsTab from '../components/LlmdLogsTab';
import { kueueStatusColor, kueueStatusLabel } from '@/shared/status';

// 后端 resolve_llmd_templates 一把出全集, 前端二分成两 tab:
// category=sglang → SGLang 引擎业务指标 (吞吐/TTFT/KV cache/队列并发);
// 其余 (gpu/cpu/memory/network) → 节点级 DCGM/cAdvisor 资源。
const SGLANG_CATEGORY = 'sglang';

const { Text } = Typography;

function podStatusColor(s: string | null | undefined): string {
  const v = (s || '').toLowerCase();
  if (/(crashloop|error|oomkilled|failed|evicted|backoff)/.test(v)) return 'error';
  if (v === 'running') return 'success';
  if (v === 'completed' || v === 'succeeded') return 'blue';
  if (/(pending|containercreating|init|waiting|schedulinggated)/.test(v)) return 'gold';
  return 'default';
}

const roleColor: Record<string, string> = {
  gateway: 'purple',
  leader: 'geekblue',
  worker: 'cyan',
};

// Go controller 写 phase + 平台哨兵 Stopped (状态直接显原始 phase, 这里只取颜色)
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

const TERMINAL = ['failed', 'Stopped'];

export default function LlmdDetailPage() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['llmd', 'common']);
  const [detail, setDetail] = useState<LlmdDetail | null>(null);
  const [wsName, setWsName] = useState<string>(t('nav.workspace'));
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [kueueWl, setKueueWl] = useState<string | null>(null);

  const fetchDetail = useCallback(
    async (sync = false, silent = false) => {
      if (!id) return;
      if (!silent) setLoading(true);
      try {
        const [d, ws] = await Promise.all([
          getLlmd(id, { sync }),
          getWorkspace(wsId).catch(() => null),
        ]);
        setDetail(d);
        if (ws) setWsName(ws.display_name);
        setErr(null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [id, wsId],
  );

  useEffect(() => {
    void fetchDetail(true, false);
  }, [fetchDetail]);

  const phase = detail?.phase as string | undefined;
  useEffect(() => {
    if (!phase || TERMINAL.includes(phase)) return;
    const timer = setInterval(() => void fetchDetail(true, true), 30_000);
    return () => clearInterval(timer);
  }, [phase, fetchDetail]);

  const handleDelete = useCallback(async () => {
    try {
      await deleteLlmd(id);
      message.success(t('messages.deleted'));
      navigate(`/workspaces/${wsId}/llmd`);
    } catch (e) {
      message.error(t('messages.deleteFailed', { error: e instanceof Error ? e.message : String(e) }));
    }
  }, [id, wsId, navigate, t]);

  const handleStop = useCallback(async () => {
    try {
      await stopLlmd(id);
      message.success(t('messages.stopped'));
      await fetchDetail(false);
    } catch (e) {
      message.error(t('messages.stopFailed', { error: e instanceof Error ? e.message : String(e) }));
    }
  }, [id, fetchDetail, t]);

  const podColumns: ColumnsType<LlmdPodSummary> = [
    { title: 'Pod', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: t('fields.role'),
      dataIndex: 'role',
      key: 'role',
      width: 90,
      render: (v: string) => (v ? <Tag color={roleColor[v] ?? 'default'}>{v}</Tag> : '-'),
    },
    { title: 'Ready', dataIndex: 'ready', key: 'ready', width: 70, render: (v) => v ?? '-' },
    {
      title: t('common:fields.status'),
      dataIndex: 'status',
      key: 'status',
      width: 170,
      render: (v: string, row) => <Tag color={podStatusColor(v)}>{v ?? row.phase ?? '-'}</Tag>,
    },
    {
      title: t('detail.pods.restarts'),
      dataIndex: 'restarts',
      key: 'restarts',
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
            <Text type="danger" style={{ fontSize: 12 }}>{v}</Text>
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

  const containerColumns: ColumnsType<LlmdContainerSummary> = [
    {
      title: t('fields.role'),
      dataIndex: 'name',
      key: 'role',
      width: 150,
      render: (name: string) => {
        const role =
          name === 'sglang'
            ? { text: t('detail.containers.roles.engine'), color: 'purple' }
            : name === 'gateway'
              ? { text: t('detail.containers.roles.gateway'), color: 'purple' }
              : (name ?? '').endsWith('-otel-collector')
                ? { text: t('detail.containers.roles.metrics'), color: 'cyan' }
                : { text: t('detail.containers.roles.other'), color: 'default' };
        return <Tag color={role.color}>{role.text}</Tag>;
      },
    },
    {
      title: t('detail.containers.name'),
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: (v: string) => <Text copyable style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: 'Ready',
      dataIndex: 'ready',
      key: 'ready',
      width: 90,
      render: (v: boolean) =>
        v ? (
          <Tag color="success">{t('detail.containers.ready')}</Tag>
        ) : (
          <Tag>{t('detail.containers.notReady')}</Tag>
        ),
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
            <Text type="danger" style={{ fontSize: 12 }}>{v}</Text>
          </Tooltip>
        ) : (
          '-'
        ),
    },
  ];

  const podGroups = useMemo(() => {
    // 分组键: LWS 按 group 序号 (组内 leader+worker 共享一个 gang Workload → 一卡);
    // gateway 按 workload_name (每副本独立 pod 级 Workload → 各自一卡, "一卡一 Workload" 全局统一)。
    const groups = new Map<string, LlmdPodSummary[]>();
    for (const p of detail?.pods ?? []) {
      const key =
        p.group != null
          ? `g:${p.group}`
          : `w:${p.workload_name ?? p.name ?? ''}`;
      const arr = groups.get(key) ?? [];
      arr.push(p);
      groups.set(key, arr);
    }
    // 排序: LWS 组 (g:) 按序号升序在前, gateway 卡片 (w:) 在后 (按 workload 名稳定排序)。
    return [...groups.entries()].sort(([a], [b]) => {
      const aG = a.startsWith('g:');
      const bG = b.startsWith('g:');
      if (aG && bG) return Number(a.slice(2)) - Number(b.slice(2));
      if (aG) return -1;
      if (bG) return 1;
      return a.localeCompare(b); // 两个 gateway 卡片: 按 workload 名稳定序
    });
  }, [detail?.pods]);

  if (err) {
    return (
      <PageContainer>
        <Alert type="error" message={t('common:messages.loadFailed')} description={err} showIcon />
      </PageContainer>
    );
  }
  if (!detail) return <PageContainer loading={loading} />;

  const meta = {
    // 状态直接显原始 phase (debug 友好); 颜色取 phaseBadge 命中色, 未命中 default
    status: phaseBadge[detail.phase as string]?.status ?? ('default' as const),
    text: (detail.phase as string) || '-',
  };

  // 存量老行 k8s_name 曾带 -gateway (未迁移), 会显示成双后缀。
  const gatewaySvc = `${detail.k8s_name}-gateway`;

  return (
    <PageContainer
      loading={loading}
      header={{
        title: detail.display_name || detail.name,
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{wsName}</a> },
            { title: <a onClick={() => navigate(`/workspaces/${wsId}/llmd`)}>{t('nav.llmd')}</a> },
            { title: detail.name },
          ],
        },
      }}
      extra={[
        <Button key="refresh" icon={<ReloadOutlined />} loading={loading} onClick={() => void fetchDetail(true)}>
          {t('detail.forceRefresh')}
        </Button>,
        <Button
          key="clone"
          icon={<CopyOutlined />}
          disabled={!detail}
          onClick={() =>
            navigate(`/workspaces/${wsId}/llmd/new?cloneFrom=${detail?.id ?? id}`)
          }
        >
          {t('actions.cloneConfig')}
        </Button>,
        ...(!TERMINAL.includes(detail.phase as string)
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
        <ProCard bordered>
          <Descriptions column={3} size="small">
            <Descriptions.Item label={t('common:fields.status')}>
              <Badge status={meta.status} text={meta.text} />
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
            <Descriptions.Item label={t('fields.scale')}>
              {t('spec.scale', {
                replicas: t('spec.replicaCount', { count: detail.replicas }),
                nodes: t('spec.nodeCount', { count: detail.nodes_per_replica }),
                gpu: t('spec.gpuCount', { count: detail.gpu_per_pod }),
              })}{' '}
              · {detail.gpu_instance_type}
            </Descriptions.Item>
            <Descriptions.Item label={t('fields.creator')}>{detail.creator_display_name}</Descriptions.Item>
            <Descriptions.Item label={t('fields.workspace')}>{detail.workspace_display_name}</Descriptions.Item>
            <Descriptions.Item label={t('detail.fields.lastSync')}>
              {detail.last_sync_at ? dayjs(detail.last_sync_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="K8s Namespace">
              <Text code>{detail.k8s_namespace}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Gateway Service">
              <Text code copyable>{gatewaySvc}</Text>
            </Descriptions.Item>
            {/* 三态: 可调用 / ALB 有地址但 gateway 未就绪 / 没开 ALB。
                后端 endpoint_url 只在两个条件都满足时才回填, 所以这里能直接分辨。 */}
            <Descriptions.Item label={t('detail.endpoint.label')} span={2}>
              {detail.endpoint_url ? (
                <Text code copyable>{detail.endpoint_url}</Text>
              ) : detail.alb_dns ? (
                <Text type="warning" style={{ fontSize: 12 }}>
                  <Trans
                    i18nKey="detail.endpoint.albReady"
                    ns="llmd"
                    components={{ dns: <Text code>{detail.alb_dns}</Text> }}
                  />
                </Text>
              ) : detail.expose_alb ? (
                // 带出口: 正常 1-2 分钟出地址。长时间不出的已知原因是节点 SG 没放行
                // 30000 (target 一直 Timeout) 或子网 IP 不够 (每 AZ 需 ≥8 个)。
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('detail.endpoint.albCreating')}
                </Text>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('detail.endpoint.disabled')}
                </Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('common:fields.createdAt')}>
              {dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
            </Descriptions.Item>
          </Descriptions>
        </ProCard>

        <ProCard title={t('detail.gateway.title')} bordered collapsible defaultCollapsed={false}>
          <Descriptions column={2} size="small" bordered labelStyle={{ width: 240 }}>
            <Descriptions.Item label={t('detail.gateway.image')} span={2}>
              <Text code copyable>{detail.gateway_image}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.gateway.instanceType')}>
              <Text code>{detail.gateway_instance_type || detail.gpu_instance_type}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.gateway.replicas')}>{detail.gateway_replicas}</Descriptions.Item>
            <Descriptions.Item label="Gateway CPU">
              {Math.round(detail.gateway_cpu_request_millicores / 1000)}{' '}
              {t('spec.unitCore', {
                count: Math.round(detail.gateway_cpu_request_millicores / 1000),
              })}
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.gateway.memory')}>
              {Math.round(detail.gateway_memory_request_mib / 1024)} GiB
            </Descriptions.Item>
            {detail.gateway_extra_args?.length ? (
              <Descriptions.Item label={t('detail.gateway.extraArgs')} span={2}>
                <Text code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', display: 'block', fontSize: 12 }}>
                  {detail.gateway_extra_args.join('\n')}
                </Text>
              </Descriptions.Item>
            ) : null}
          </Descriptions>
        </ProCard>

        <ProCard title={t('detail.worker.title')} bordered collapsible defaultCollapsed={false}>
          <Descriptions column={2} size="small" bordered labelStyle={{ width: 240 }}>
            <Descriptions.Item label={t('detail.worker.sglangImage')} span={2}>
              <Text code copyable>{detail.sglang_image}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.modelSource')}>
              <Tag color={detail.model_source_type === 's3' ? 'green' : 'blue'}>
                {detail.model_source_type === 's3' ? 'S3' : 'FSx Lustre'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.modelMount')}>
              {detail.model_source_type === 's3' ? (
                <Space size={4}>
                  <Text code>{detail.s3_bucket || '-'}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {detail.s3_prefix ? `/${detail.s3_prefix}` : ''}
                  </Text>
                </Space>
              ) : (
                <Text code>{detail.model_pvc || '-'}</Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.instanceType')}>
              <Text code>{detail.gpu_instance_type}</Text>
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.replicas')}>{detail.replicas}</Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.nodesPerGroup')}>{detail.nodes_per_replica}</Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.gpuPerPod')}>
              {detail.gpu_per_pod} {t('spec.unitCard', { count: detail.gpu_per_pod })}
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.efaPerPod')}>
              {detail.efa_per_pod} {t('spec.unitAdapter', { count: detail.efa_per_pod })}
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.cpuPerPod')}>
              {Math.round(detail.cpu_request_millicores / 1000)}{' '}
              {t('spec.unitCore', { count: Math.round(detail.cpu_request_millicores / 1000) })}
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.memoryPerPod')}>
              {Math.round(detail.memory_request_mib / 1024)} GiB
            </Descriptions.Item>
            <Descriptions.Item label={t('detail.worker.launchScript')} span={2}>
              <Text code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', display: 'block', fontSize: 12 }}>
                {detail.launch_script || '-'}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="Labels" span={2}>
              {detail.labels && Object.keys(detail.labels).length ? (
                <Space wrap>
                  {Object.entries(detail.labels).map(([k, v]) => (
                    <Tag key={k}>{k}={v}</Tag>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">{t('detail.worker.none')}</Text>
              )}
            </Descriptions.Item>
            {detail.description && (
              <Descriptions.Item label={t('common:fields.description')} span={2}>{detail.description}</Descriptions.Item>
            )}
          </Descriptions>
        </ProCard>

        <ProCard title={t('detail.pods.title', { total: detail.pods.length })} bordered collapsible defaultCollapsed={false}>
          {podGroups.length === 0 ? (
            <Text type="secondary">{t('detail.pods.empty')}</Text>
          ) : (
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              {podGroups.map(([key, groupPods]) => {
                const wlName = groupPods.find((p) => p.workload_name)?.workload_name ?? null;
                const isGateway = key.startsWith('w:');
                const title = isGateway
                  ? t('detail.pods.groupGateway')
                  : t('detail.pods.groupReplica', { index: key.slice(2) });
                return (
                  <ProCard
                    key={key}
                    type="inner"
                    bordered
                    title={
                      <Space>
                        <span>{title}</span>
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
                    <Table<LlmdPodSummary>
                      rowKey={(r, idx) => r.name ?? `${idx}`}
                      columns={podColumns}
                      dataSource={groupPods}
                      pagination={false}
                      size="small"
                      scroll={{ x: 'max-content' }}
                      expandable={{
                        expandedRowRender: (r) => (
                          <Table<LlmdContainerSummary>
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

        <ProCard title={t('detail.timeline')} bordered>
          <ConditionsTimeline conditions={detail.conditions} />
        </ProCard>
      </Space>
            ),
          },
          {
            key: 'metrics',
            label: t('detail.tabs.monitoring'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listLlmdTemplates(detail.id);
                  return all.filter((tpl) => tpl.category !== SGLANG_CATEGORY);
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
                  const all = await listLlmdTemplates(detail.id);
                  return all.filter((tpl) => tpl.category === SGLANG_CATEGORY);
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
            children: <LlmdLogsTab llmdId={detail.id} />,
          },
        ]}
      />

      <KueueDetailDrawer
        // key=workload 名: 切换到另一个 workload 链接时强制 remount 抽屉重新 fetch。
        // 抽屉按 open 边沿触发 fetch, 一任务多 workload 时不 remount 会显示上一个的旧 conditions。
        key={kueueWl ?? 'closed'}
        open={kueueWl != null}
        onClose={() => setKueueWl(null)}
        fetcher={() => getLlmdKueueDetail(id, kueueWl as string)}
      />
    </PageContainer>
  );
}
