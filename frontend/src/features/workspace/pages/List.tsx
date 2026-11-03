import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Result,
  Row,
  Segmented,
  Select,
  Skeleton,
  Table,
  Tooltip,
  Typography,
  message,
  theme,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  AppstoreOutlined,
  CloudOutlined,
  ClockCircleOutlined,
  DownOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  TeamOutlined,
  UnorderedListOutlined,
  UpOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { ApiError } from '@/shared/api';
import {
  createWorkspace,
  listWorkspaces,
  type Workspace,
} from '@/features/workspace/api';
import {
  listClusters,
  type ClusterListItem,
} from '@/features/admin/api/cluster';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
  type ComputeQuota,
  type QuotaUsage,
} from '@/features/quota/api';
import QuotaResourcePicker, {
  type QuotaResourceRow,
} from '@/features/quota/components/QuotaResourcePicker';
import PageDescription from '@/shared/ui/PageDescription';

/**
 * Pair of quota config + live usage for one workspace. `usage=null` means
 * the Kueue-backed usage endpoint is unavailable; UI must degrade gracefully.
 */
interface WorkspaceQuotaSnapshot {
  quota: ComputeQuota;
  usage: QuotaUsage | null;
}
import { useAppStore } from '@/store';

dayjs.extend(relativeTime);

const { Text, Title, Paragraph } = Typography;

const SLUG_PATTERN = /^[a-z][a-z0-9-]{2,62}$/;

/** Map workspace.status → Badge status (K8s / AWS Console standard). */
const statusBadge = (
  s: string,
): 'success' | 'warning' | 'error' | 'default' | 'processing' => {
  switch (s) {
    case 'active':
      return 'success';
    case 'suspended':
      return 'warning';
    case 'deleting':
      return 'error';
    default:
      return 'default';
  }
};

/** workspace.status → workspace ns 里的 key (渲染时再翻译)。 */
const STATUS_LABEL_KEY = {
  active: 'status.active',
  suspended: 'status.suspended',
  deleting: 'status.deleting',
} as const;

/**
 * Workspace 创建表单字段.
 *
 * - namespace 不再可编辑, 后端从 name 派生 (hyperpod-ns-{name})
 * - 借/还 / 抢占策略 不暴露 (后端默认 DontLend / Never)
 * - resources 多行, 每行选一个集群里实际存在的机型 + 数量
 *   (机型选择 + 剩余容量逻辑已抽到 QuotaResourcePicker 共享组件)
 */
interface WorkspaceCreateFormValues {
  cluster_id: string;
  name: string;
  display_name: string;
  description?: string;
  resources: QuotaResourceRow[];
}

export default function WorkspaceList() {
  const { t } = useTranslation(['workspace', 'common']);
  const statusLabel = (s: string): string =>
    Object.hasOwn(STATUS_LABEL_KEY, s) ? t(STATUS_LABEL_KEY[s as keyof typeof STATUS_LABEL_KEY]) : s;
  const navigate = useNavigate();
  const setCurrentWorkspaceId = useAppStore((s) => s.setCurrentWorkspaceId);
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin === true;
  const { token } = theme.useToken();
  const [keyword, setKeyword] = useState('');
  // 视图切换 · 卡片(默认) / 表格. 仅 UI 状态, 不持久化。
  const [viewMode, setViewMode] = useState<'cards' | 'list'>('cards');
  const [tipOpen, setTipOpen] = useState(false);

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [clusters, setClusters] = useState<ClusterListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // per-workspace: quota + usage 异步逐个填(单 ws 慢不阻塞别的卡片)
  const [quotaMap, setQuotaMap] = useState<Record<string, WorkspaceQuotaSnapshot | null>>({});

  const [modalOpen, setModalOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<WorkspaceCreateFormValues>();

  // 选中集群 → QuotaResourcePicker 自己拉机型 + 算剩余
  const [selectedClusterId, setSelectedClusterId] = useState<string | undefined>();
  // 用户在 name 字段输入的 slug, 用于实时算 namespace 预览
  const nameWatch = Form.useWatch('name', form);

  // Phase 1: 主信息 (workspaces), 立即可见.
  // Phase 2: 每个 ws 独立异步拉 quota + usage, 单个完成单个 setState 填入.
  // 设计目的: 列表卡片 1s 内出现, GPU 数据陆续填; 单 ws 慢不阻塞别的卡片.
  // clusters 推迟到 "新建工作空间" Modal 打开时再拉 (列表页本身不展示集群信息).
  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setQuotaMap({});
    try {
      // ===== Phase 1: workspaces (主信息阻塞) =====
      // 可见范围由后端按已认证身份强制过滤 (超管→全部, 普通用户→自己 owner+member),
      // 前端不再传 user_id 自决可见性 (越权修复 2026-06-14)。
      const ws = await listWorkspaces();
      setWorkspaces(ws);
      setLoading(false); // 卡片立即出现, 后面是异步填充

      // ===== Phase 2: 每个 ws 独立异步拉 quota + usage =====
      // 不 await, 后台跑. 每个 ws 完成时单独 setState 填进 quotaMap.
      for (const w of ws) {
        void (async () => {
          const [quotaRes, usageRes] = await Promise.allSettled([
            getWorkspaceQuota(w.id),
            getWorkspaceQuotaUsage(w.id),
          ]);
          const snapshot: WorkspaceQuotaSnapshot | null =
            quotaRes.status === 'fulfilled'
              ? {
                  quota: quotaRes.value,
                  usage: usageRes.status === 'fulfilled' ? usageRes.value : null,
                }
              : null;
          setQuotaMap((prev) => ({ ...prev, [w.id]: snapshot }));
        })();
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      setError(msg || t('common:messages.loadFailed'));
      setLoading(false);
    }
  }, [t]);

  // 拉 clusters · 仅在 "新建工作空间" Modal 打开时调用 (列表页不需要).
  // 返新拉到的 list 给 caller (caller 用它默认选中第一个 cluster, 不靠 setState 时序).
  const loadClustersIfNeeded = useCallback(async (): Promise<ClusterListItem[]> => {
    if (clusters.length > 0) return clusters;
    try {
      const cls = await listClusters();
      setClusters(cls);
      return cls;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      message.error(msg || t('list.messages.loadClustersFailed'));
      return [];
    }
  }, [clusters, t]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const filtered = useMemo(
    () =>
      workspaces.filter((w) =>
        (w.display_name + w.name + w.namespace)
          .toLowerCase()
          .includes(keyword.toLowerCase()),
      ),
    [workspaces, keyword],
  );

  // 标题副标摘要: 空间数 / 成员总数 / GPU 总配额使用 (M/P 卡 + %)。
  // 成员数走 ws.member_count (后端字段, 0 额外调用); GPU 走已拉到的 quotaMap (异步逐个填,
  // 没拉完时按已知部分累加, 跟卡片配额数据同源)。
  const headerSummary = useMemo(() => {
    const wsCount = workspaces.length;
    const memberCount = workspaces.reduce(
      (acc, w) => acc + (w.member_count ?? 0),
      0,
    );
    let gpuTotalQuota = 0;
    let gpuTotalUsed = 0;
    let usageReady = false; // 至少有一个 ws 已拉到 usage 才显使用量
    workspaces.forEach((w) => {
      const snap = quotaMap[w.id];
      if (!snap) return;
      gpuTotalQuota += aggregateQuota(snap.quota.resources).totalAccelerators;
      if (snap.usage) {
        gpuTotalUsed += snap.usage.totals.accelerators ?? 0;
        usageReady = true;
      }
    });
    const pct = gpuTotalQuota > 0 ? Math.round((gpuTotalUsed / gpuTotalQuota) * 100) : 0;
    return { wsCount, memberCount, gpuTotalQuota, gpuTotalUsed, usageReady, pct };
  }, [workspaces, quotaMap]);

  // 表格列 (list 视图) · 字段与卡片信息一致, 加紧凑展示。
  const tableColumns: ColumnsType<Workspace> = useMemo(
    () => [
      {
        title: t('common:fields.name'),
        dataIndex: 'display_name',
        key: 'display_name',
        render: (_: unknown, ws: Workspace) => (
          <div>
            <Typography.Text strong>{ws.display_name}</Typography.Text>
            <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              {ws.name}
            </Typography.Text>
          </div>
        ),
        sorter: (a, b) => a.display_name.localeCompare(b.display_name),
      },
      {
        title: 'Namespace',
        dataIndex: 'namespace',
        key: 'namespace',
        width: 220,
        render: (v: string) => (
          <Typography.Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</Typography.Text>
        ),
      },
      {
        title: t('common:fields.status'),
        dataIndex: 'status',
        key: 'status',
        width: 110,
        render: (s: string) => <Badge status={statusBadge(s)} text={statusLabel(s)} />,
        filters: [
          { text: t('status.active'), value: 'active' },
          { text: t('status.suspended'), value: 'suspended' },
          { text: t('status.deleting'), value: 'deleting' },
        ],
        onFilter: (value, ws) => ws.status === value,
      },
      {
        title: t('list.columns.gpuUsage'),
        key: 'gpu',
        width: 160,
        render: (_: unknown, ws: Workspace) => {
          const quotaLoading = !(ws.id in quotaMap);
          const snapshot = quotaMap[ws.id] ?? null;
          if (quotaLoading) return <Typography.Text type="secondary">{t('common:messages.loading')}</Typography.Text>;
          if (snapshot === null) return <Typography.Text type="secondary">{t('list.notConfigured')}</Typography.Text>;
          const gpuQuota = aggregateQuota(snapshot.quota.resources).totalAccelerators;
          if (gpuQuota === 0) return <Typography.Text type="secondary">{t('list.none')}</Typography.Text>;
          const used = snapshot.usage?.totals.accelerators ?? null;
          if (used === null) return <span>{t('list.cards', { count: gpuQuota })}</span>;
          const pct = Math.round((used / gpuQuota) * 100);
          return (
            <span>
              {t('list.usedOfCards', { used, count: gpuQuota })}{' '}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                ({pct}%)
              </Typography.Text>
            </span>
          );
        },
        sorter: (a, b) => {
          const ga = quotaMap[a.id]
            ? aggregateQuota(quotaMap[a.id]!.quota.resources).totalAccelerators
            : 0;
          const gb = quotaMap[b.id]
            ? aggregateQuota(quotaMap[b.id]!.quota.resources).totalAccelerators
            : 0;
          return ga - gb;
        },
      },
      {
        title: t('list.columns.members'),
        dataIndex: 'member_count',
        key: 'member_count',
        width: 90,
        render: (n: number) => t('list.peopleCount', { count: n }),
        sorter: (a, b) => a.member_count - b.member_count,
      },
      {
        title: t('common:fields.description'),
        dataIndex: 'description',
        key: 'description',
        ellipsis: true,
        render: (d?: string) =>
          d ? (
            <Tooltip title={d}>
              <span>{d}</span>
            </Tooltip>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              -
            </Typography.Text>
          ),
      },
      {
        title: t('common:fields.createdAt'),
        dataIndex: 'created_at',
        key: 'created_at',
        width: 140,
        render: (v: string) => (
          <Tooltip title={dayjs(v).format('YYYY-MM-DD HH:mm:ss')}>
            <span>{dayjs(v).fromNow()}</span>
          </Tooltip>
        ),
        sorter: (a, b) => dayjs(a.created_at).valueOf() - dayjs(b.created_at).valueOf(),
        defaultSortOrder: 'descend',
      },
      // 快捷编辑 (仅平台管理员): 跳到详情页对应 tab
      ...(isAdmin
        ? [
            {
              title: t('list.columns.quickEdit'),
              key: 'edit',
              width: 200,
              fixed: 'right' as const,
              render: (_: unknown, ws: Workspace) => (
                <span onClick={(e) => e.stopPropagation()}>
                  <Tooltip title={t('list.quickEdit.members')}>
                    <Button
                      size="small"
                      type="text"
                      icon={<TeamOutlined />}
                      onClick={() => navigate(`/workspaces/${ws.id}?tab=members`)}
                    >
                      {t('list.quickEdit.membersShort')}
                    </Button>
                  </Tooltip>
                  <Tooltip title={t('list.quickEdit.fsx')}>
                    <Button
                      size="small"
                      type="text"
                      icon={<FolderOpenOutlined />}
                      onClick={() => navigate(`/workspaces/${ws.id}?tab=fsx`)}
                    >
                      FSx
                    </Button>
                  </Tooltip>
                  <Tooltip title={t('list.quickEdit.s3')}>
                    <Button
                      size="small"
                      type="text"
                      icon={<CloudOutlined />}
                      onClick={() => navigate(`/workspaces/${ws.id}?tab=s3`)}
                    >
                      S3
                    </Button>
                  </Tooltip>
                </span>
              ),
            },
          ]
        : []),
    ],
    [quotaMap, isAdmin, navigate, t],
  );

  const enterWorkspace = (wsId: string) => {
    setCurrentWorkspaceId(wsId);
    navigate(`/workspaces/${wsId}`);
  };

  const handleOpenCreate = async () => {
    // 先拉集群 + 选好默认集群, 再开 Modal —— 这样 Modal 打开、form 挂载、picker 渲染时,
    // selectedClusterId 与 initialValues.cluster_id 都已就绪, picker 的 clusterTag 直接
    // 有值, 不走 fallback、不出现"集群暂无机型"黄 banner 的空窗。
    const cls = await loadClustersIfNeeded();
    if (cls.length > 0) {
      setSelectedClusterId(cls[0].id);
    }
    setModalOpen(true);
  };

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setCreating(true);
      // namespace 由后端从 name 派生 (hyperpod-ns-{name}), 前端不发
      // 借/还 / 抢占 走后端默认 (DontLend / Never), 不传
      // resources 至少 1 行: AWS CreateComputeQuota 要求长度 >=1
      // 新版 picker 把整个集群机型都列出来, 未分配机型 count=0; 提交前过滤 0 行.
      const resources = (values.resources ?? [])
        .filter((r) => r?.instance_type && (r.count ?? 0) > 0)
        .map((r) => ({
          instance_type: r.instance_type,
          count: r.count,
        }));
      if (resources.length === 0) {
        message.error(t('list.messages.needOneType'));
        return;
      }
      const created = await createWorkspace({
        cluster_id: values.cluster_id,
        name: values.name.trim(),
        display_name: values.display_name.trim(),
        description: values.description?.trim() || undefined,
        resources,
      });
      message.success(t('list.messages.created'));
      setModalOpen(false);
      // 跳详情页, admin 在那里继续配 FSx + 成员
      setCurrentWorkspaceId(created.id);
      navigate(`/workspaces/${created.id}`);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          form.setFields([
            { name: 'name', errors: [e.message || t('list.messages.nameTaken')] },
          ]);
        } else {
          message.error(e.message || t('list.messages.createFailed'));
        }
      } else if ((e as { errorFields?: unknown }).errorFields) {
        // antd form validation error — 无需 toast
      } else {
        message.error((e as Error).message || t('list.messages.createFailed'));
      }
    } finally {
      setCreating(false);
    }
  };

  return (
    <PageContainer
      title={t('list.title')}
      extra={[
        <Input.Search
          key="search"
          allowClear
          placeholder={t('list.searchPlaceholder')}
          style={{ width: 280 }}
          onSearch={setKeyword}
          onChange={(e) => setKeyword(e.target.value)}
        />,
        <Segmented
          key="view"
          value={viewMode}
          onChange={(v) => setViewMode(v as 'cards' | 'list')}
          options={[
            { value: 'cards', icon: <AppstoreOutlined /> },
            { value: 'list', icon: <UnorderedListOutlined /> },
          ]}
        />,
        // 仅平台管理员可见 · 普通成员不展示"新建"按钮
        ...(isAdmin
          ? [
              <Button
                key="create"
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleOpenCreate}
                loading={loading}
              >
                {t('list.createButton')}
              </Button>,
            ]
          : []),
      ]}
    >
      <PageDescription>
        {t('list.description')}{' '}
        {isAdmin ? t('list.descriptionAdmin') : t('list.descriptionMember')}
      </PageDescription>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('list.intro.title')}
        action={
          <a
            onClick={() => setTipOpen((v) => !v)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 12,
            }}
          >
            <span>{tipOpen ? t('common:actions.collapse') : t('common:actions.expand')}</span>
            {tipOpen ? (
              <UpOutlined style={{ fontSize: 11 }} />
            ) : (
              <DownOutlined style={{ fontSize: 11 }} />
            )}
          </a>
        }
        description={
          tipOpen ? (
            <div style={{ lineHeight: 1.8 }}>
              <div style={{ marginBottom: 8 }}>
                <b>{t('list.intro.whatIs')}</b>
              </div>
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>
                  <Trans i18nKey="list.intro.resourceBoundary" ns="workspace" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans i18nKey="list.intro.permissionBoundary" ns="workspace" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans i18nKey="list.intro.assetBoundary" ns="workspace" components={{ b: <b /> }} />
                </li>
              </ul>

              <div style={{ marginBottom: 8 }}>
                <b>{t('list.intro.k8sMapping')}</b>
                <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                  {t('list.intro.k8sMappingHint')}
                </span>
              </div>
              <ul style={{ margin: '0 0 12px', paddingLeft: 20 }}>
                <li>
                  <Trans
                    i18nKey="list.intro.k8sNamespace"
                    ns="workspace"
                    components={{ b: <b />, code: <code>{t('list.intro.k8sNamespacePattern')}</code> }}
                  />
                </li>
                <li>
                  <Trans i18nKey="list.intro.k8sResourceQuota" ns="workspace" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans
                    i18nKey="list.intro.k8sKueue"
                    ns="workspace"
                    components={{ b: <b />, code: <code /> }}
                  />
                </li>
                <li>
                  <Trans i18nKey="list.intro.k8sComputeQuota" ns="workspace" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans i18nKey="list.intro.k8sIamRole" ns="workspace" components={{ b: <b /> }} />
                </li>
              </ul>

              <div
                style={{
                  marginTop: 4,
                  padding: '8px 12px',
                  background: 'rgba(0,0,0,0.02)',
                  borderRadius: 6,
                  fontSize: 12,
                  color: 'rgba(0,0,0,0.55)',
                }}
              >
                <Trans i18nKey="list.intro.summary" ns="workspace" components={{ b: <b /> }} />
              </div>
            </div>
          ) : null
        }
      />
      {/* mini-dashboard: 标题下汇总 chip 行, 单行不占地方但比纯文字醒目 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 0,
          marginBottom: 16,
          background: token.colorFillQuaternary,
          borderRadius: 8,
          padding: '10px 16px',
          flexWrap: 'wrap',
        }}
      >
        {(() => {
          const gpuColor =
            !headerSummary.usageReady
              ? token.colorTextSecondary
              : headerSummary.pct >= 90
                ? token.colorError
                : headerSummary.pct >= 70
                  ? token.colorWarning
                  : token.colorSuccess;
          const statItem = (
            icon: React.ReactNode,
            label: string,
            value: React.ReactNode,
          ) => (
            <div style={{ display: 'flex', alignItems: 'stretch', gap: 8, padding: '0 16px' }}>
              <span
                style={{
                  width: 36,
                  borderRadius: 8,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: token.colorBgContainer,
                  color: token.colorPrimary,
                  fontSize: 16,
                  flexShrink: 0,
                }}
              >
                {icon}
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                <Typography.Text type="secondary" style={{ fontSize: 11, letterSpacing: 0.4 }}>
                  {label}
                </Typography.Text>
                <span style={{ fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                  {value}
                </span>
              </div>
            </div>
          );
          const divider = (
            <span
              style={{
                width: 1,
                height: 26,
                background: token.colorBorderSecondary,
              }}
            />
          );
          return (
            <>
              {statItem(<AppstoreOutlined />, t('list.summary.workspaces'), `${headerSummary.wsCount}`)}
              {divider}
              {statItem(<TeamOutlined />, t('list.summary.totalMembers'), `${headerSummary.memberCount}`)}
              {divider}
              {statItem(
                <CloudOutlined />,
                t('list.summary.totalGpuUsage'),
                headerSummary.usageReady ? (
                  <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {headerSummary.gpuTotalUsed}
                    <Typography.Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                      {' '}/ {t('list.cards', { count: headerSummary.gpuTotalQuota })}
                    </Typography.Text>
                    <span
                      style={{
                        marginLeft: 6,
                        fontSize: 13,
                        color: gpuColor,
                        fontWeight: 500,
                      }}
                    >
                      {headerSummary.pct}%
                    </span>
                  </span>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                    {t('list.summary.computing')}
                  </Typography.Text>
                ),
              )}
            </>
          );
        })()}
      </div>

      {error ? (
        <Result
          status="error"
          title={t('list.loadFailed')}
          subTitle={error}
          extra={
            <Button type="primary" onClick={() => void loadAll()}>
              {t('common:actions.retry')}
            </Button>
          }
        />
      ) : loading ? (
        <Row gutter={[16, 16]}>
          {[0, 1, 2].map((i) => (
            <Col key={i} xs={24} md={12} xl={8}>
              <Card style={{ borderRadius: 12 }}>
                <Skeleton active paragraph={{ rows: 3 }} />
              </Card>
            </Col>
          ))}
        </Row>
      ) : filtered.length === 0 ? (
        <Card style={{ borderRadius: 12 }}>
          <Empty
            description={
              workspaces.length === 0
                ? isAdmin
                  ? t('list.empty.admin')
                  : t('list.empty.member')
                : t('list.empty.noMatch')
            }
          >
            {workspaces.length === 0 && isAdmin && (
              <Button type="primary" icon={<PlusOutlined />} onClick={handleOpenCreate}>
                {t('list.empty.createNow')}
              </Button>
            )}
          </Empty>
        </Card>
      ) : viewMode === 'list' ? (
        <Card style={{ borderRadius: 12 }} styles={{ body: { padding: 0 } }}>
          <Table<Workspace>
            rowKey="id"
            columns={tableColumns}
            dataSource={filtered}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            onRow={(ws) => ({
              onClick: () => enterWorkspace(ws.id),
              style: { cursor: 'pointer' },
            })}
          />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {filtered.map((ws) => {
            // 三态: undefined=还在拉(loading), null=拉失败/未配置, snapshot=已拉到
            const quotaLoading = !(ws.id in quotaMap);
            const snapshot = quotaMap[ws.id] ?? null;
            const gpuQuota = snapshot
              ? aggregateQuota(snapshot.quota.resources).totalAccelerators
              : 0;
            const gpuUsed: number | null =
              snapshot?.usage?.totals.accelerators ?? null;
            const hasUsage = gpuUsed !== null;
            const gpuPct =
              hasUsage && gpuQuota > 0
                ? Math.round(((gpuUsed as number) / gpuQuota) * 100)
                : 0;

            // 配色阈值与详情页 (Dashboard.tsx · colorFor) 对齐: <70 success / 70-90 warning / >=90 error
            const gpuStrokeColor =
              gpuPct >= 90
                ? token.colorError
                : gpuPct >= 70
                  ? token.colorWarning
                  : token.colorSuccess;
            const gpuStatusText: string | null = quotaLoading
              ? t('common:messages.loading')
              : snapshot === null
                ? t('list.notConfigured')
                : gpuQuota === 0
                  ? t('list.noGpuQuota')
                  : !hasUsage
                    ? t('list.quotaCollecting', { count: gpuQuota })
                    : null;
            const gpuBlock = (
              <div style={{ marginBottom: 14 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    marginBottom: 2,
                  }}
                >
                  <Text type="secondary" style={{ fontSize: 11, letterSpacing: 0.4 }}>
                    {t('list.currentGpuUsage')}
                  </Text>
                  {gpuStatusText ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {gpuStatusText}
                    </Text>
                  ) : (
                    <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: 13 }}>
                      <Text strong style={{ fontSize: 14 }}>
                        {gpuUsed}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {' '}/ {t('list.cards', { count: gpuQuota })}
                      </Text>
                      <Text
                        style={{
                          fontSize: 12,
                          marginLeft: 6,
                          color: gpuStrokeColor,
                          fontWeight: 500,
                        }}
                      >
                        {gpuPct}%
                      </Text>
                    </span>
                  )}
                </div>
                <Progress
                  percent={gpuStatusText ? 0 : Math.max(0, Math.min(100, gpuPct))}
                  showInfo={false}
                  size="small"
                  strokeColor={gpuStatusText ? token.colorBorderSecondary : gpuStrokeColor}
                  style={{ marginTop: 2 }}
                />
              </div>
            );

            return (
              <Col key={ws.id} xs={24} md={12} xl={8}>
                <Card
                  hoverable
                  style={{ borderRadius: 12, height: '100%' }}
                  styles={{ body: { padding: 20 } }}
                  onClick={() => enterWorkspace(ws.id)}
                >
                  {/* 标题区: 大字 display_name + name 副标 + 右上 status 徽标 */}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                      gap: 12,
                    }}
                  >
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <Title
                        level={4}
                        style={{ margin: 0, marginBottom: 2, fontWeight: 600 }}
                        ellipsis={{ tooltip: ws.display_name }}
                      >
                        {ws.display_name}
                      </Title>
                      <Text
                        type="secondary"
                        style={{ fontSize: 13 }}
                        ellipsis
                      >
                        {ws.name}
                      </Text>
                    </div>
                    <Badge
                      status={statusBadge(ws.status)}
                      text={
                        <Text style={{ fontSize: 12, fontWeight: 500 }}>
                          {statusLabel(ws.status)}
                        </Text>
                      }
                    />
                  </div>

                  {/* 描述: 占位高度固定避免卡片高度参差 */}
                  <Paragraph
                    type="secondary"
                    ellipsis={{ rows: 2, tooltip: ws.description || undefined }}
                    style={{
                      marginTop: 12,
                      marginBottom: 0,
                      fontSize: 13,
                      minHeight: 40,
                      lineHeight: '20px',
                    }}
                  >
                    {ws.description || (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {t('list.noDescription')}
                      </Text>
                    )}
                  </Paragraph>

                  {/* GPU 使用 (独立一段, 进度条全宽; label 和数字分居两端) */}
                  <div
                    style={{
                      marginTop: 16,
                      paddingTop: 16,
                      borderTop: `1px solid ${token.colorBorderSecondary}`,
                    }}
                  >
                    {gpuBlock}
                    {/* 横排两列 KV (Namespace · 成员) */}
                    <KvRow
                      label="Namespace"
                      value={
                        <Text
                          copyable={{ tooltips: [t('common:actions.copy'), t('common:messages.copied')] }}
                          style={{
                            fontSize: 13,
                            fontFamily: 'monospace',
                          }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {ws.namespace}
                        </Text>
                      }
                    />
                    <KvRow
                      label={t('list.columns.members')}
                      value={t('list.peopleCount', { count: ws.member_count })}
                    />
                  </div>

                  {/* 快捷编辑 (仅平台管理员): 跳到详情页对应 tab; stopPropagation 防触发卡片整体跳转 */}
                  {isAdmin && (
                    <div
                      style={{
                        marginTop: 12,
                        paddingTop: 12,
                        borderTop: `1px dashed ${token.colorBorderSecondary}`,
                        display: 'flex',
                        gap: 4,
                        flexWrap: 'wrap',
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Tooltip title={t('list.quickEdit.members')}>
                        <Button
                          size="small"
                          type="text"
                          icon={<TeamOutlined />}
                          onClick={() => navigate(`/workspaces/${ws.id}?tab=members`)}
                        >
                          {t('list.quickEdit.membersShort')}
                        </Button>
                      </Tooltip>
                      <Tooltip title={t('list.quickEdit.fsx')}>
                        <Button
                          size="small"
                          type="text"
                          icon={<FolderOpenOutlined />}
                          onClick={() => navigate(`/workspaces/${ws.id}?tab=fsx`)}
                        >
                          FSx
                        </Button>
                      </Tooltip>
                      <Tooltip title={t('list.quickEdit.s3')}>
                        <Button
                          size="small"
                          type="text"
                          icon={<CloudOutlined />}
                          onClick={() => navigate(`/workspaces/${ws.id}?tab=s3`)}
                        >
                          S3
                        </Button>
                      </Tooltip>
                    </div>
                  )}

                  {/* footer: 创建时间 */}
                  <div
                    style={{
                      marginTop: 16,
                      paddingTop: 12,
                      borderTop: `1px dashed ${token.colorBorderSecondary}`,
                    }}
                  >
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      <ClockCircleOutlined style={{ marginRight: 4 }} />
                      {t('list.createdAgo', { time: dayjs(ws.created_at).fromNow() })}
                    </Text>
                  </div>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      <Modal
        title={t('list.createModal.title')}
        open={modalOpen}
        onOk={() => void handleCreate()}
        confirmLoading={creating}
        onCancel={() => setModalOpen(false)}
        okText={t('common:actions.create')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
        width={680}
      >
        <Alert
          type="info"
          showIcon
          message={t('list.createModal.hint')}
          style={{ marginBottom: 16 }}
        />
        {clusters.length === 0 && (
          <Alert
            type="warning"
            showIcon
            message={t('list.createModal.noClusters')}
            description={t('list.createModal.noClustersDesc')}
            style={{ marginBottom: 16 }}
          />
        )}
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{
            cluster_id: clusters[0]?.id,
            // 新版 picker 自动把集群所有机型补成 count=0 行, 不预填占位行
            resources: [],
          }}
          onValuesChange={(changed) => {
            if ('cluster_id' in changed) {
              setSelectedClusterId(changed.cluster_id as string | undefined);
              // 不再手动清空 resources: picker 的 SyncListWithCluster 已改为按新集群
              // 机型原子重排 (旧机型自动丢弃), clusterTypes 一变就同步。手动清空反而
              // 在"选中的就是默认集群 (值没变 → picker 不重拉)"时把行清没了 → N/A。
            }
          }}
        >
          <Form.Item
            name="cluster_id"
            label={t('list.createModal.cluster')}
            rules={[{ required: true, message: t('list.createModal.clusterRequired') }]}
          >
            <Select
              placeholder={t('list.createModal.clusterPlaceholder')}
              options={clusters.map((c) => ({
                label: `${c.cluster_tag} (${c.type} · ${c.region})`,
                value: c.id,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label={t('list.createModal.nameLabel')}
            tooltip={t('list.createModal.nameTooltip')}
            rules={[
              { required: true, message: t('list.createModal.nameRequired') },
              {
                pattern: SLUG_PATTERN,
                message: t('list.createModal.namePattern'),
              },
            ]}
          >
            <Input placeholder={t('list.createModal.namePlaceholder')} autoComplete="off" />
          </Form.Item>
          <Form.Item label={t('list.createModal.namespaceLabel')}>
            <Input
              value={nameWatch ? `hyperpod-ns-${nameWatch}` : ''}
              placeholder={t('list.createModal.namespacePlaceholder')}
              readOnly
              disabled
            />
          </Form.Item>
          <Form.Item
            name="display_name"
            label={t('list.createModal.displayName')}
            rules={[
              { required: true, message: t('list.createModal.displayNameRequired') },
              { max: 128, message: t('list.createModal.displayNameMax') },
            ]}
          >
            <Input placeholder={t('list.createModal.displayNamePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('list.createModal.descriptionLabel')}>
            <Input.TextArea rows={2} placeholder={t('list.createModal.descriptionPlaceholder')} />
          </Form.Item>

          <Divider orientation="left" plain style={{ marginTop: 8 }}>
            {t('list.createModal.quotaDivider')}
          </Divider>
          <QuotaResourcePicker
            clusterTag={
              clusters.find((c) => c.id === selectedClusterId)?.cluster_tag
            }
          />
        </Form>
      </Modal>
    </PageContainer>
  );
}

interface KvRowProps {
  label: string;
  value: React.ReactNode;
}

/** 卡片信息区一行 · 左 label 灰小字 · 右 value 中等粗体. */
function KvRow({ label, value }: KvRowProps) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '6px 0',
        minHeight: 28,
      }}
    >
      <Text type="secondary" style={{ fontSize: 12 }}>
        {label}
      </Text>
      {typeof value === 'string' ? (
        <Text style={{ fontSize: 14, fontWeight: 500 }}>{value}</Text>
      ) : (
        value
      )}
    </div>
  );
}
