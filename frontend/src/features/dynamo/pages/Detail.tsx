import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  Alert,
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
import { DeleteOutlined, PoweroffOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { deleteDynamo, getDynamo, stopDynamo } from '../api/client';
import type { DynamoDetail, DynamoPodSummary } from '../api/types';
import { getWorkspace } from '@/features/workspace/api';
import ConditionsTimeline from '@/shared/ui/ConditionsTimeline';
import MonitoringTabPanel from '@/shared/ui/metrics/MonitoringTabPanel';
import { listDynamoTemplates } from '@/api/monitoring';
import InvokeSnippets from '../components/InvokeSnippets';
import DynamoLogsTab from '../components/DynamoLogsTab';

const { Text } = Typography;

function podStatusColor(s: string | null | undefined): string {
  const v = (s || '').toLowerCase();
  if (/(crashloop|error|oomkilled|failed|evicted|backoff)/.test(v)) return 'error';
  if (v === 'running') return 'success';
  if (v === 'completed' || v === 'succeeded') return 'blue';
  if (/(pending|containercreating|init|waiting|schedulinggated)/.test(v)) return 'gold';
  return 'default';
}

// status.state enum (实测) + 平台哨兵 Stopped (状态直接显原始 phase, 这里只取颜色)
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

export default function DynamoDetailPage() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['dynamo', 'common']);
  const [detail, setDetail] = useState<DynamoDetail | null>(null);
  const [wsName, setWsName] = useState<string>(t('nav.workspace'));
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const fetchDetail = useCallback(
    async (sync = false, silent = false) => {
      if (!id) return;
      if (!silent) setLoading(true);
      try {
        const [d, ws] = await Promise.all([
          getDynamo(id, { sync }),
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
      await deleteDynamo(id);
      message.success(t('messages.deleted'));
      navigate(`/workspaces/${wsId}/dynamo`);
    } catch (e) {
      message.error(t('messages.deleteFailed', { error: e instanceof Error ? e.message : String(e) }));
    }
  }, [id, wsId, navigate, t]);

  const handleStop = useCallback(async () => {
    try {
      await stopDynamo(id);
      message.success(t('messages.stopped'));
      await fetchDetail(false);
    } catch (e) {
      message.error(t('messages.stopFailed', { error: e instanceof Error ? e.message : String(e) }));
    }
  }, [id, fetchDetail, t]);

  const podColumns: ColumnsType<DynamoPodSummary> = [
    { title: 'Pod', dataIndex: 'name', key: 'name', ellipsis: true },
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

  if (err) {
    return (
      <PageContainer>
        <Alert type="error" message={t('common:messages.loadFailed')} description={err} showIcon />
      </PageContainer>
    );
  }
  if (!detail) return <PageContainer loading={loading} />;

  const meta = {
    // 状态直接显原始 CR phase (debug 友好, 与推理/训练/开发机一致); 颜色取 phaseBadge 命中色, 未命中 default
    status: phaseBadge[detail.phase as string]?.status ?? ('default' as const),
    text: (detail.phase as string) || '-',
  };

  const overview = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <ProCard bordered>
        <Descriptions column={3} size="small">
          <Descriptions.Item label={t('common:fields.status')}>
            <Tag color={meta.status === 'success' ? 'green' : meta.status === 'error' ? 'red' : undefined}>
              {meta.text}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.summary.kueueStatus')}>
            {detail.kueue_status || '-'}
          </Descriptions.Item>
          <Descriptions.Item label={t('fields.scale')}>
            {t('spec.scale', {
              replicas: t('spec.replicaCount', { count: detail.replicas }),
              nodes: t('spec.nodeCount', { count: detail.node_count }),
              gpu: t('spec.gpuCount', { count: detail.gpu_per_worker }),
            })}{' '}
            · {detail.instance_type}
          </Descriptions.Item>
          <Descriptions.Item label={t('fields.framework')}>
            <Tag color="purple">{(detail.backend_framework || 'sglang').toUpperCase()}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('fields.creator')}>{detail.creator_display_name}</Descriptions.Item>
          <Descriptions.Item label={t('fields.workspace')}>{detail.workspace_display_name}</Descriptions.Item>
          <Descriptions.Item label={t('detail.fields.lastSync')}>
            {detail.last_sync_at ? dayjs(detail.last_sync_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="K8s Namespace">
            <Text code>{detail.k8s_namespace}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="CR Name">
            <Text code>{detail.k8s_cr_name}</Text>
          </Descriptions.Item>
          <Descriptions.Item label={t('common:fields.createdAt')}>
            {dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}
          </Descriptions.Item>
        </Descriptions>
      </ProCard>

      <ProCard title={t('detail.config.title')} bordered collapsible defaultCollapsed={false}>
        <Descriptions column={2} size="small" bordered labelStyle={{ width: 240 }}>
          <Descriptions.Item label={t('detail.config.image')} span={2}>
            <Text code copyable>{detail.image}</Text>
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.modelSource')}>
            <Tag>{detail.model_source_type === 's3' ? 'S3' : 'FSx Lustre'}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.modelMount')}>
            {detail.model_source_type === 's3' && detail.s3 ? (
              <Text>
                <Text code>{detail.s3.bucket_name}</Text>
                <Text type="secondary"> / {detail.s3.model_location}</Text>
              </Text>
            ) : (
              <Text code>{detail.fsx_pvc_name || '-'}</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.instanceType')}>
            <Text code>{detail.instance_type}</Text>
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.nodeCount')}>{detail.node_count}</Descriptions.Item>
          <Descriptions.Item label={t('detail.config.replicas')}>{detail.replicas}</Descriptions.Item>
          <Descriptions.Item label={t('detail.config.gpuPerNode')}>
            {detail.gpu_per_worker} {t('spec.unitCard', { count: detail.gpu_per_worker })}
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.efaPerNode')}>
            {detail.efa_per_worker} {t('spec.unitAdapter', { count: detail.efa_per_worker })}
          </Descriptions.Item>
          <Descriptions.Item label="CPU (req/lim)">
            {(detail.cpu_request_millicores / 1000).toFixed(1)} / {(detail.cpu_limit_millicores / 1000).toFixed(1)}{' '}
            {t('spec.unitCore', { count: 2 })}
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.memory')}>
            {(detail.memory_request_mib / 1024).toFixed(1)} / {(detail.memory_limit_mib / 1024).toFixed(1)} GiB
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.runAsRoot')}>
            <Tag color={detail.run_as_root ? 'gold' : 'default'}>
              {detail.run_as_root ? t('detail.config.runAsRootYes') : t('detail.config.runAsRootNo')}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t('detail.config.launchScript')} span={2}>
            <pre
              style={{
                background: '#f5f5f5',
                padding: 12,
                borderRadius: 4,
                fontSize: 12,
                margin: 0,
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
                userSelect: 'text',
              }}
            >
              {detail.launch_script || t('detail.config.defaultLaunch')}
            </pre>
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
          {detail.description && (
            <Descriptions.Item label={t('common:fields.description')} span={2}>{detail.description}</Descriptions.Item>
          )}
        </Descriptions>
      </ProCard>

      <ProCard title={t('detail.pods.title', { total: detail.pods.length })} bordered collapsible defaultCollapsed={false}>
        <Table<DynamoPodSummary>
          rowKey={(r, idx) => r.name ?? `${idx}`}
          columns={podColumns}
          dataSource={detail.pods}
          pagination={false}
          size="small"
          scroll={{ x: 'max-content' }}
          locale={{ emptyText: t('detail.pods.empty') }}
        />
      </ProCard>

      <ProCard title={t('detail.timeline')} bordered>
        <ConditionsTimeline conditions={detail.conditions} />
      </ProCard>

      <InvokeSnippets detail={detail} />
    </Space>
  );

  return (
    <PageContainer
      loading={loading}
      header={{
        title: detail.display_name || detail.name,
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{wsName}</a> },
            { title: <a onClick={() => navigate(`/workspaces/${wsId}/dynamo`)}>{t('nav.dynamo')}</a> },
            { title: detail.name },
          ],
        },
      }}
      extra={[
        <Button key="refresh" icon={<ReloadOutlined />} loading={loading} onClick={() => void fetchDetail(true)}>
          {t('detail.forceRefresh')}
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
          { key: 'overview', label: t('detail.tabs.overview'), children: overview },
          {
            key: 'metrics',
            label: t('detail.tabs.monitoring'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listDynamoTemplates(detail.id);
                  return all.filter((tpl) => tpl.category !== 'dynamo');
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
            key: 'engine',
            label: t('detail.tabs.engine'),
            children: (
              <MonitoringTabPanel
                loadTemplates={async () => {
                  const all = await listDynamoTemplates(detail.id);
                  return all.filter((tpl) => tpl.category === 'dynamo');
                }}
                depKey={`${detail.id}-engine`}
                height={220}
                banner={
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 16 }}
                    message={t('detail.engineBanner')}
                  />
                }
              />
            ),
          },
          {
            key: 'logs',
            label: t('detail.tabs.logs'),
            children: detail ? <DynamoLogsTab dynamoId={detail.id} /> : null,
          },
        ]}
      />
    </PageContainer>
  );
}
