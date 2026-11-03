import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer, ProCard, ProDescriptions } from '@ant-design/pro-components';
import {
  App,
  Alert,
  Badge,
  Button,
  Col,
  Empty,
  Popconfirm,
  Row,
  Skeleton,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  ApiOutlined,
  ControlOutlined,
  CopyOutlined,
  DeleteOutlined,
  DesktopOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  ShareAltOutlined,
  StopOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useTranslation } from 'react-i18next';
import {
  buildProxyUrl,
  deleteDevInstance,
  getAccessInfo,
  getDevInstance,
  getDevInstanceKueueDetail,
  getDevInstanceStatusDetail,
  startDevInstance,
  stopDevInstance,
} from '../api/client';
import KueueDetailDrawer from '@/shared/components/KueueDetailDrawer';
import DevInstanceLogsTab from '../components/DevInstanceLogsTab';
import type {
  AccessInfo,
  DevInstanceCondition,
  DevInstanceDetail as DevInstanceDetailType,
} from '../api/types';
import { ApiError } from '@/shared/api';
import { POOL_LABEL, type Pool } from '@/api/resource-pool';
import { phaseColor } from '@/shared/status';
import KueueStatusField from '@/shared/ui/KueueStatusField';
import CrPhaseField from '@/shared/ui/CrPhaseField';
import StatusDetailDrawer from '@/shared/ui/StatusDetailDrawer';
import MonitoringTabPanel from '@/shared/ui/metrics/MonitoringTabPanel';
import {
  instantQuery,
  listDevInstanceKpi,
  listDevInstanceTemplates,
  type QueryTemplate,
} from '@/api/monitoring';
import ConnectModal from '../components/ConnectModal';
import ResizeModal from '../components/ResizeModal';
import ConditionsTimeline from '@/shared/ui/ConditionsTimeline';
import ShareModal from '@/features/sharing/ShareModal';
import { useAppStore } from '@/store';

function formatDuration(from: string | null | undefined): string {
  if (!from) return '-';
  const diff = dayjs().diff(dayjs(from), 'second');
  if (diff < 60) return `${diff}s`;
  const min = Math.floor(diff / 60);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ${min % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export default function DevDetail() {
  const { wsId = '', id = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation(['devinstance', 'common']);
  const { message } = App.useApp();

  const [instance, setInstance] = useState<DevInstanceDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [access, setAccess] = useState<AccessInfo | null>(null);
  // "Kueue 详情" 抽屉: 实时查 Workload conditions + admission
  const [kueueOpen, setKueueOpen] = useState(false);
  // "CR 详情" 弹窗: 只读看原始 CR status_detail (同列表页放大镜 icon)
  const [crDetailOpen, setCrDetailOpen] = useState(false);
  // 分享弹窗 (仅 creator 本人可见入口)
  const [shareOpen, setShareOpen] = useState(false);
  const currentUser = useAppStore((s) => s.currentUser);
  const [kpis, setKpis] = useState<{ tpl: QueryTemplate; value: number | null }[]>([]);

  const load = useCallback(
    // retryOnFail: 失败时先静默重试一次再报错 (吞掉首屏偶发抖动: 后端冷启动/
    // token 刷新瞬间 401/网络抖动 —— 重试即好, 不该弹错误 toast 吓用户)。
    async (silent = false, retryOnFail = false) => {
      if (!id) return;
      if (!silent) setLoading(true);
      try {
        const detail = await getDevInstance(id);
        setInstance(detail);
      } catch (err) {
        if (retryOnFail) {
          await new Promise((r) => setTimeout(r, 800));
          try {
            const detail = await getDevInstance(id);
            setInstance(detail);
            return;
          } catch (err2) {
            message.error(
              err2 instanceof ApiError
                ? err2.message
                : t('common:messages.loadFailed'),
            );
            return;
          }
        }
        if (!silent) {
          message.error(
            err instanceof ApiError ? err.message : t('common:messages.loadFailed'),
          );
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [id, message, t],
  );

  useEffect(() => {
    // 首屏偶发失败先静默重试一次, 避免错误 toast 一闪。
    load(false, true);
    const timer = setInterval(() => load(true), 15_000);
    return () => clearInterval(timer);
  }, [load]);

  // phase 变化 (如 Stop→Start) 时清 access 缓存: 停启期间 SSH Service 会短暂
  // 消失/重建, 强制下次打开重新拉最新 directSSH 连接信息。
  useEffect(() => {
    setAccess(null);
  }, [instance?.phase]);

  // Load KPI templates once the instance is known, then poll each instant query.
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    const loadKpis = async () => {
      try {
        const tpls = await listDevInstanceKpi(id);
        const results = await Promise.all(
          tpls.map(async (tpl) => {
            try {
              const resp = await instantQuery(tpl.promql);
              const vec = resp.data?.result as
                | { value: [number, string] }[]
                | undefined;
              if (!vec || vec.length === 0) return { tpl, value: null };
              // Take the max across all series (pod / gpu) so a single card
              // summarizes the whole dev-instance even with multiple GPUs.
              const max = vec.reduce(
                (m, r) => Math.max(m, Number(r.value[1]) || 0),
                Number.NEGATIVE_INFINITY,
              );
              return { tpl, value: Number.isFinite(max) ? max : null };
            } catch {
              return { tpl, value: null };
            }
          }),
        );
        if (!cancelled) setKpis(results);
      } catch {
        if (!cancelled) setKpis([]);
      }
    };
    void loadKpis();
    const timer = setInterval(loadKpis, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [id]);

  const [connectOpen, setConnectOpen] = useState(false);
  const [accessLoading, setAccessLoading] = useState(false);
  const [resizeOpen, setResizeOpen] = useState(false);

  // 抓最新 access info (directSSH: ssh_hostname + ssh_command + ssh_config_snippet)。
  // 给「连接」按钮和 Modal 内的「刷新」共用。DNS 记录同步约 30-60s, 未就绪时刷新即可。
  const refreshAccess = useCallback(async () => {
    setAccessLoading(true);
    try {
      const info = await getAccessInfo(id);
      setAccess(info);
      return info;
    } catch (err) {
      message.error(
        err instanceof ApiError ? err.message : t('detail.getAccessFailed'),
      );
      return null;
    } finally {
      setAccessLoading(false);
    }
  }, [id, message, t]);

  const handleConnect = () => {
    setConnectOpen(true);
    void refreshAccess();
  };

  const handleStop = async () => {
    setActionLoading(true);
    try {
      await stopDevInstance(id);
      message.success(t('messages.stopSent'));
      // Pod 即将销毁 · SSH Service 随之消失 · 强制下次点连接时重抓
      setAccess(null);
      await load(true);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('messages.stopFailed'));
    } finally {
      setActionLoading(false);
    }
  };

  const handleStart = async () => {
    setActionLoading(true);
    try {
      await startDevInstance(id);
      message.success(t('messages.startSent'));
      // 新 Pod 起来后 addon 重建 SSH Service · 清缓存下次重抓固定 DNS
      setAccess(null);
      await load(true);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('messages.startFailed'));
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteDevInstance(id);
      message.success(t('messages.deleted'));
      navigate(`/workspaces/${wsId}/dev`);
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('messages.deleteFailed'));
    }
  };

  if (loading) {
    return (
      <PageContainer title={t('detail.title')}>
        <ProCard>
          <Skeleton active />
        </ProCard>
      </PageContainer>
    );
  }

  if (!instance) {
    return (
      <PageContainer title={t('detail.title')}>
        <ProCard>
          <Empty description={t('detail.notFound')} />
        </ProCard>
      </PageContainer>
    );
  }

  const meta = {
    // 直接显原始 CR phase (与 List 一致, debug 友好); 颜色仍走 phaseColor 兜底
    label: instance.phase || '-',
    status: phaseColor(instance.phase),
  };
  const running = (instance.phase || '').includes('Available');
  const stopped = (instance.phase || '').includes('Stopped');

  const specText = `${(instance.cpu_request_millicores / 1000).toFixed(1)} CPU · ${(
    instance.memory_request_mib / 1024
  ).toFixed(1)} GiB · ${instance.gpu_count} GPU${
    instance.efa_count > 0 ? ` · ${instance.efa_count} EFA` : ''
  } · ${instance.storage_size_gib} GiB EBS`;

  // 后端 conditions: list[dict[str, Any]] · openapi schema 是 unknown[]
  // 这里 cast 成前端约定的 DevInstanceCondition (frontend-only type), 见 ../api/types.ts
  const conditions = (instance.conditions ?? []) as DevInstanceCondition[];

  return (
    <PageContainer
      header={{
        title: (
          <Space>
            <span>{instance.display_name}</span>
            <Badge status={meta.status} text={meta.label} />
          </Space>
        ),
        breadcrumb: {
          items: [
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{t('nav.workspace')}</a> },
            { title: <a onClick={() => navigate(`/workspaces/${wsId}/dev`)}>{t('nav.devInstance')}</a> },
            { title: instance.name },
          ],
        },
      }}
      extra={[
        <Button key="refresh" icon={<ReloadOutlined />} onClick={() => load()}>
          {t('common:actions.refresh')}
        </Button>,
        <Button
          key="clone"
          icon={<CopyOutlined />}
          onClick={() =>
            navigate(`/workspaces/${wsId}/dev/new?cloneFrom=${instance?.id ?? id}`)
          }
        >
          {t('actions.cloneConfig')}
        </Button>,
        // 分享: 仅 creator 本人可见 (被分享者进详情页无此入口, 不能二次转分享)
        instance.creator_user_id === currentUser?.id ? (
          <Button
            key="share"
            icon={<ShareAltOutlined />}
            onClick={() => setShareOpen(true)}
          >
            {t('actions.share')}
          </Button>
        ) : null,
        instance.creator_user_id === currentUser?.id ? (
          <Popconfirm
            key="delete"
            title={t('confirm.deleteTitleGeneric')}
            description={t('confirm.deleteDesc')}
            okType="danger"
            okText={t('common:actions.delete')}
            cancelText={t('common:actions.cancel')}
            onConfirm={handleDelete}
          >
            <Button danger icon={<DeleteOutlined />}>
              {t('common:actions.delete')}
            </Button>
          </Popconfirm>
        ) : null,
      ]}
    >
      {/* 页头摘要 + 主操作 + EBS 提示 三合一: 状态/规格/操作都属于同层级摘要,
          原本分三张卡视觉割裂, 合并到一张 ProCard 内, 用 Divider 轻分隔 */}
      <ProCard style={{ marginBottom: 16 }} bordered>
        <Row gutter={24} align="middle">
          <Col flex="auto">
            <Space size="large" wrap>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('detail.summary.crStatus')}
                </Typography.Text>
                <CrPhaseField
                  status={meta.status}
                  text={meta.label}
                  onShowDetail={() => setCrDetailOpen(true)}
                />
              </Space>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('detail.summary.kueueStatus')}
                </Typography.Text>
                <KueueStatusField
                  status={instance.kueue_status}
                  onShowDetail={() => setKueueOpen(true)}
                />
              </Space>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('common:fields.duration')}
                </Typography.Text>
                <Typography.Text>
                  {running ? formatDuration(instance.started_at) : '-'}
                </Typography.Text>
              </Space>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('fields.image')}
                </Typography.Text>
                <Typography.Text code style={{ fontSize: 12 }}>
                  {instance.image.split('/').pop()}
                </Typography.Text>
              </Space>
              <Space direction="vertical" size={0}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('fields.spec')}
                </Typography.Text>
                <Typography.Text>{specText}</Typography.Text>
              </Space>
            </Space>
          </Col>
        </Row>

        <div
          style={{
            margin: '16px 0',
            borderTop: '1px solid rgba(5, 5, 5, 0.06)',
          }}
        />

        <Space size="middle" wrap>
          {running && (
            <Popconfirm
              title={t('confirm.stopTitle')}
              description={t('confirm.stopDesc')}
              onConfirm={handleStop}
            >
              <Button icon={<StopOutlined />} loading={actionLoading}>
                {t('common:actions.stop')}
              </Button>
            </Popconfirm>
          )}
          {stopped && (
            <Button
              icon={<PlayCircleOutlined />}
              loading={actionLoading}
              onClick={handleStart}
            >
              {t('common:actions.start')}
            </Button>
          )}
          {/* 改规格仅创建者本人 (会重建 Pod、改账单); 被分享者/管理员/超管无此入口 */}
          {instance.creator_user_id === currentUser?.id && (
            <Button
              icon={<ControlOutlined />}
              disabled={!running && !stopped}
              onClick={() => setResizeOpen(true)}
            >
              {t('actions.resize')}
            </Button>
          )}
          <Button
            type="primary"
            icon={<ApiOutlined />}
            disabled={!running}
            onClick={handleConnect}
          >
            {t('actions.connect')}
          </Button>
          <Button
            icon={<DesktopOutlined />}
            disabled={!running}
            onClick={() =>
              window.open(
                // JupyterLab 设了 base_url, 根路径 / 返回 404, 入口是 /lab;
                // Code Editor 直接走根路径。
                buildProxyUrl(
                  id,
                  instance?.app_type === 'code-editor' ? '' : 'lab',
                ),
                '_blank',
                'noopener',
              )
            }
          >
            {instance?.app_type === 'code-editor'
              ? t('actions.openCodeEditor')
              : t('actions.openJupyterLab')}
          </Button>
        </Space>

        {/* EBS 卷生命周期提示 · 与上方"停止/连接"操作语义直接相关, 留在同卡内底部 */}
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          showIcon
          message={t('detail.ebsNote')}
        />
      </ProCard>

      <ConnectModal
        open={connectOpen}
        access={access}
        loading={accessLoading}
        onClose={() => setConnectOpen(false)}
        onRefresh={refreshAccess}
      />

      <ResizeModal
        wsId={wsId}
        instance={instance}
        open={resizeOpen}
        onClose={() => setResizeOpen(false)}
        onSuccess={() => load(true)}
      />

      {/* Tabs: 总览 (实例详情 + Conditions) / 监控 — 对齐训练/推理详情结构 */}
      <Tabs
        defaultActiveKey="overview"
        destroyInactiveTabPane
        items={[
          {
            key: 'overview',
            label: t('detail.tabs.overview'),
            children: (
              <>
      {/* 详情 + Conditions */}
      <Row gutter={[16, 16]} align="stretch">
        <Col xs={24} xl={12}>
          <ProCard title={t('detail.cards.instance')} bordered style={{ height: '100%' }}>
            <ProDescriptions
              column={1}
              dataSource={instance}
              columns={[
                {
                  title: t('detail.fields.nameDisplay'),
                  render: () => `${instance.name} / ${instance.display_name}`,
                },
                { title: t('common:fields.description'), dataIndex: 'description' },
                { title: t('fields.template'), dataIndex: 'template_name' },
                // 资源池: 创建时选了池才显示 (老数据无 pool 不占一行)
                ...(instance.pool
                  ? [
                      {
                        title: t('fields.resourcePool'),
                        render: () => (
                          <Tag color={instance.pool === 'gpu' ? 'blue' : 'green'}>
                            {t('detail.fields.poolTag', {
                              pool: POOL_LABEL[instance.pool as Pool] ?? instance.pool,
                            })}
                          </Tag>
                        ),
                      },
                    ]
                  : []),
                // 实例类型: 仅创建时选了机型才显示 (未选 = 调度器分配, 不占一行)
                ...(instance.instance_type
                  ? [
                      {
                        title: t('detail.fields.instanceType'),
                        render: () => instance.instance_type,
                      },
                    ]
                  : []),
                { title: 'AppType', dataIndex: 'app_type' },
                { title: t('fields.image'), dataIndex: 'image', copyable: true },
                {
                  title: t('detail.fields.priority'),
                  render: () =>
                    instance.priority_class ? (
                      <Typography.Text code style={{ fontSize: 12 }}>
                        {instance.priority_class}
                      </Typography.Text>
                    ) : (
                      <Typography.Text type="secondary">
                        {t('detail.fields.priorityDefault')}
                      </Typography.Text>
                    ),
                },
                {
                  title: t('detail.fields.mounts'),
                  render: () => {
                    const mounts = instance.volume_mounts ?? [];
                    if (mounts.length === 0) return t('detail.fields.notMounted');
                    return (
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        {mounts.map((m) => {
                          const pvc = m.pvc_name ?? '';
                          const isFsx = pvc.includes('-fsx-');
                          // FSx: ro/rw 从 PVC 名后缀推断 (pvc-ws-fsx-<id>-rw / -ro)。
                          // S3: 全局只读 (mount-s3 read-only), 一律显示只读。
                          const access = !isFsx
                            ? 'ro'
                            : pvc.endsWith('-ro')
                              ? 'ro'
                              : pvc.endsWith('-rw')
                                ? 'rw'
                                : null;
                          return (
                            <Space key={m.pvc_name} size={6}>
                              <Tag color={isFsx ? 'geekblue' : 'purple'}>
                                {isFsx ? 'FSx' : 'S3'}
                              </Tag>
                              {access && (
                                <Tag color={access === 'rw' ? 'gold' : 'default'}>
                                  {access === 'rw'
                                    ? t('common:storagePicker.readWrite')
                                    : t('common:storagePicker.readOnly')}
                                </Tag>
                              )}
                              <Typography.Text code style={{ fontSize: 12 }}>
                                {m.mount_path}
                              </Typography.Text>
                              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                                {m.pvc_name}
                              </Typography.Text>
                            </Space>
                          );
                        })}
                      </Space>
                    );
                  },
                },
                { title: 'K8s Namespace', dataIndex: 'k8s_namespace' },
                { title: 'K8s Workspace', dataIndex: 'k8s_workspace_name' },
                {
                  title: t('common:fields.createdAt'),
                  dataIndex: 'created_at',
                  render: (v) =>
                    v ? dayjs(v as string).format('YYYY-MM-DD HH:mm:ss') : '-',
                },
                { title: t('detail.fields.creator'), dataIndex: 'creator_display_name' },
              ]}
            />
          </ProCard>
        </Col>
        <Col xs={24} xl={12}>
          <ProCard
            title={t('detail.cards.timeline')}
            bordered
            style={{ height: '100%' }}
          >
            <ConditionsTimeline conditions={conditions} />
            {instance.last_condition_message && (
              <Alert
                style={{ marginTop: 12 }}
                type={(instance.phase || '').includes('Degraded') ? 'error' : 'info'}
                showIcon
                message={t('detail.lastStatus', {
                  message: instance.last_condition_message,
                })}
              />
            )}
          </ProCard>
        </Col>
      </Row>

              </>
            ),
          },
          {
            key: 'monitoring',
            label: t('detail.tabs.monitoring'),
            children: (
              <>
                {/* 顶部 3 KPI 卡 */}
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  {kpis.map(({ tpl, value }) => (
                    <Col key={tpl.key} xs={24} md={8}>
                      <ProCard bordered bodyStyle={{ padding: 12 }}>
                        <Statistic
                          title={tpl.title}
                          value={value ?? '-'}
                          precision={value !== null && value < 10 ? 2 : 0}
                          suffix={
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {tpl.unit}
                            </Typography.Text>
                          }
                        />
                        {tpl.description && (
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                            {tpl.description}
                          </Typography.Text>
                        )}
                      </ProCard>
                    </Col>
                  ))}
                </Row>
                <MonitoringTabPanel
                  loadTemplates={() => listDevInstanceTemplates(id)}
                  depKey={id}
                  height={220}
                  banner={null}
                />
              </>
            ),
          },
          {
            key: 'logs',
            label: t('detail.tabs.logs'),
            children: <DevInstanceLogsTab devInstanceId={id} />,
          },
        ]}
      />

      <KueueDetailDrawer
        open={kueueOpen}
        onClose={() => setKueueOpen(false)}
        fetcher={() => getDevInstanceKueueDetail(id)}
      />

      <StatusDetailDrawer
        open={crDetailOpen}
        title={t('statusDetailTitle')}
        detailId={crDetailOpen ? id : null}
        fetcher={getDevInstanceStatusDetail}
        onClose={() => setCrDetailOpen(false)}
      />
      <ShareModal
        wsId={wsId}
        resType="dev"
        resId={instance.id}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
      />
    </PageContainer>
  );
}
