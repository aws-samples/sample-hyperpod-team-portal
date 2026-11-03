import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Progress,
  Result,
  Row,
  Skeleton,
  Space,
  Tabs,
  Tooltip,
  Typography,
  message,
  theme,
} from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import {
  ClockCircleOutlined,
  ClusterOutlined,
  DatabaseOutlined,
  DesktopOutlined,
  EditOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { ApiError } from '@/shared/api';
import {
  getWorkspace,
  updateWorkspace,
  type WorkspaceDetail,
  type WorkspaceFsxMount,
  type WorkspaceS3Mount,
} from '@/features/workspace/api';
import FsxTab from './FsxTab';
import MembersTab from './MembersTab';
import S3Tab from './S3Tab';
import WorkspaceGpuUtilChart from '../components/WorkspaceGpuUtilChart';
import { useIsWsAdmin } from '@/features/workspace/hooks/useIsWsAdmin';
import { useAppStore } from '@/store';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
  updateComputeQuota,
  type ComputeQuota,
  type ComputeQuotaResource,
  type QuotaUsage,
} from '@/features/quota/api';
import QuotaResourcePicker, {
  type QuotaResourceRow,
} from '@/features/quota/components/QuotaResourcePicker';
/** Paired config + live usage snapshot. `usage=null` when Kueue endpoint degrades. */
interface WorkspaceQuotaSnapshot {
  quota: ComputeQuota;
  usage: QuotaUsage | null;
}

dayjs.extend(relativeTime);

const { Text } = Typography;

// 资源池预览最多显示几种机型, 超出折叠成"显示全部"弹框
const POOL_PREVIEW_MAX = 4;

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
  suspended: 'status.paused',
  deleting: 'status.deleting',
} as const;

export default function WorkspaceDashboard() {
  const { t } = useTranslation(['workspace', 'common']);
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // 支持 ?tab=fsx|s3|members|overview 直接打开指定 tab (List 页快捷编辑入口用)。
  // 切换 tab 时同步更新 URL, 让浏览器后退能回到上一个 tab。
  const activeTab = searchParams.get('tab') || 'overview';
  // canManage = 平台超管 OR 该 ws 的 admin 成员 (与后端 assert_ws_admin 同口径),
  // 让 ws 管理员也能看到成员/S3/FSx/配额等管理操作。
  const { canManage } = useIsWsAdmin(wsId);
  // isPlatformAdmin = 仅平台超管 (区别于 ws 管理员)。FsxTab 用它分流目录数据源
  // (超管走原接口不筛 gid) + 控制卸载按钮显隐 (卸载保留超管)。
  const isPlatformAdmin = useAppStore((s) => s.currentUser?.is_admin === true);

  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  // Quota state is independent from the workspace load — a quota API outage
  // should not blank out the whole dashboard, just show a subdued fallback.
  const [snapshot, setSnapshot] = useState<WorkspaceQuotaSnapshot | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const [quotaError, setQuotaError] = useState<string | null>(null);

  // 编辑基本信息 (展示名 + 描述) · admin only
  const [editInfoOpen, setEditInfoOpen] = useState(false);
  const [savingInfo, setSavingInfo] = useState(false);
  const [infoForm] = Form.useForm<{ display_name: string; description?: string }>();

  // 调整配额 (机型 + 数量) · admin only
  const [editQuotaOpen, setEditQuotaOpen] = useState(false);
  const [savingQuota, setSavingQuota] = useState(false);
  const [quotaForm] = Form.useForm<{ resources: QuotaResourceRow[] }>();
  // 打开 Modal 时快照当前 resources, 作 Form initialValues (Form.List 在异步
  // 子组件 QuotaResourcePicker 里, 用 initialValues 比 afterOpenChange+setFieldsValue
  // 可靠 — 不受 picker loading 时序影响).
  const [quotaInitial, setQuotaInitial] = useState<QuotaResourceRow[]>([]);

  // Mount summaries · 直接从 workspace.metadata_json 派生 (concept GET ws 已经返了
  // fsx_mounts / s3_mounts 完整列表). 不另发 /fsx /s3 请求, 省 2 次 AWS round-trip.
  // metadata_json 缺 name/capacity_gib/dns_name 字段, 但 Dashboard 概览卡不展示这些.
  const fsxMounts = (
    (workspace?.metadata_json?.fsx_mounts as unknown) as WorkspaceFsxMount[] | undefined
  ) ?? [];
  const s3Mounts = (
    (workspace?.metadata_json?.s3_mounts as unknown) as WorkspaceS3Mount[] | undefined
  ) ?? [];

  const load = useCallback(async () => {
    if (!wsId) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const ws = await getWorkspace(wsId);
      setWorkspace(ws);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setNotFound(true);
      } else {
        setError(e instanceof ApiError ? e.message : (e as Error).message);
      }
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  useEffect(() => {
    void load();
  }, [load]);

  // 拉 quota + usage · 既给首次 effect 用, 也给"调整配额"保存后刷新用
  const reloadQuota = useCallback(async () => {
    if (!wsId) return;
    setQuotaLoading(true);
    setQuotaError(null);
    const [quotaRes, usageRes] = await Promise.allSettled([
      getWorkspaceQuota(wsId),
      getWorkspaceQuotaUsage(wsId),
    ]);
    if (quotaRes.status !== 'fulfilled') {
      const e = quotaRes.reason;
      const msg =
        e instanceof ApiError
          ? `${e.status} ${e.message}`
          : e instanceof Error
            ? e.message
            : String(e);
      setQuotaError(msg);
      setSnapshot(null);
    } else {
      setSnapshot({
        quota: quotaRes.value,
        usage: usageRes.status === 'fulfilled' ? usageRes.value : null,
      });
    }
    setQuotaLoading(false);
  }, [wsId]);

  useEffect(() => {
    void reloadQuota();
  }, [reloadQuota]);

  // ===== 编辑基本信息 =====
  // 注: 表单预填放在 Modal afterOpenChange (表单挂载后) 做, 不能在 openEditInfo
  // 里直接 setFieldsValue — destroyOnClose 下表单此刻还没挂载, 值会丢.
  const openEditInfo = () => {
    setEditInfoOpen(true);
  };

  const fillInfoForm = (open: boolean) => {
    if (!open) return;
    infoForm.setFieldsValue({
      display_name: workspace?.display_name ?? '',
      description: workspace?.description ?? '',
    });
  };

  const handleSaveInfo = async () => {
    try {
      const values = await infoForm.validateFields();
      setSavingInfo(true);
      await updateWorkspace(wsId, {
        display_name: values.display_name.trim(),
        description: values.description?.trim() || undefined,
      });
      message.success(t('dashboard.messages.infoUpdated'));
      setEditInfoOpen(false);
      await load();
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(e.message);
      } else if ((e as { errorFields?: unknown }).errorFields) {
        // form validation - silent
      } else {
        message.error((e as Error).message || t('dashboard.messages.saveFailed'));
      }
    } finally {
      setSavingInfo(false);
    }
  };

  // ===== 调整配额 =====
  // 打开前快照当前 resources 作 initialValues, 再开 Modal.
  const openEditQuota = () => {
    const cur = snapshot?.quota.resources ?? [];
    setQuotaInitial(
      cur.length
        ? cur.map((r) => ({ instance_type: r.instanceType, count: r.count }))
        : [{ instance_type: undefined as unknown as string, count: 1 }],
    );
    setEditQuotaOpen(true);
  };

  // 表单预填放在 Modal afterOpenChange (表单挂载后) 做。
  // ⚠️ 不能只靠 Form initialValues: quotaForm 实例常驻 (非随 destroyOnClose 销毁),
  // antd 仅在实例首次接管字段时应用 initialValues; 第二次打开实例已 touch 过 →
  // 不再重读 initialValues → 已有机型行不预填 (现象: 再次打开机型行为空)。
  // 与 fillInfoForm 同模式: 每次打开都显式 setFieldsValue, 用快照当前 resources。
  const fillQuotaForm = (open: boolean) => {
    if (!open) return;
    const cur = snapshot?.quota.resources ?? [];
    // 新版 picker 自己会把"集群所有机型"补成 row (count=0), 这里只填已存在的占用,
    // 未占用机型由 picker 的 SyncListWithCluster effect 补 0 行. 不再塞空 instance_type 占位.
    quotaForm.setFieldsValue({
      resources: cur.map((r) => ({
        instance_type: r.instanceType,
        count: r.count,
      })),
    });
  };

  const handleSaveQuota = async () => {
    try {
      const values = await quotaForm.validateFields();
      // 新版 picker 把所有集群机型都列出来 (count=0 表示"未分配"), 提交前过滤 0 行,
      // 后端只接受 count≥1 的实际占用; 同时挡住 instance_type 缺失的脏行.
      const rows = (values.resources ?? []).filter(
        (r) => r?.instance_type && (r.count ?? 0) > 0,
      );
      if (rows.length === 0) {
        message.error(t('dashboard.messages.needOneType'));
        return;
      }
      // QuotaResourceRow (snake) → AWS quota payload (camel).
      // 只发 instanceType + count: 后端 Count 路径下 accelerators 被忽略,
      // 规格由后端回填, 无需前端推断。
      const resources = rows.map((r) => ({
        instanceType: r.instance_type,
        count: r.count,
      }));
      setSavingQuota(true);
      await updateComputeQuota(wsId, { resources });
      message.success(t('dashboard.messages.quotaUpdated'));
      setEditQuotaOpen(false);
      await reloadQuota();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          message.error(t('dashboard.messages.quotaConflict'));
        } else {
          message.error(e.message);
        }
      } else if ((e as { errorFields?: unknown }).errorFields) {
        // form validation - silent
      } else {
        message.error((e as Error).message || t('dashboard.messages.saveFailed'));
      }
    } finally {
      setSavingQuota(false);
    }
  };

  if (notFound) {
    return (
      <PageContainer>
        <Result
          status="404"
          title={t('dashboard.notFound.title')}
          subTitle={t('dashboard.notFound.subTitle', { wsId })}
          extra={
            <Button type="primary" onClick={() => navigate('/workspaces')}>
              {t('dashboard.notFound.backToList')}
            </Button>
          }
        />
      </PageContainer>
    );
  }

  if (error) {
    return (
      <PageContainer>
        <Result
          status="error"
          title={t('dashboard.loadFailed')}
          subTitle={error}
          extra={
            <Button type="primary" onClick={() => void load()}>
              {t('common:actions.retry')}
            </Button>
          }
        />
      </PageContainer>
    );
  }

  if (loading || !workspace) {
    return (
      <PageContainer>
        <Card style={{ borderRadius: 12 }}>
          <Skeleton active paragraph={{ rows: 4 }} />
        </Card>
      </PageContainer>
    );
  }

  return (
    <PageContainer
      header={{
        title: (
          <Space size={10} align="baseline" wrap>
            <span style={{ fontSize: 20, fontWeight: 700 }}>
              {workspace.display_name}
            </span>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {workspace.name}
            </Text>
          </Space>
        ),
        // 描述紧跟标题: 单行紧凑显示, 末尾带编辑 icon (admin 才出); 与训练/推理详情同套路
        subTitle: (
          <Space size={6} align="center" style={{ marginTop: 2 }}>
            {workspace.description ? (
              <Text type="secondary" style={{ fontSize: 13 }}>
                {workspace.description}
              </Text>
            ) : (
              <Text type="secondary" style={{ fontSize: 13, fontStyle: 'italic' }}>
                {t('dashboard.noDescription')}
              </Text>
            )}
            {canManage && (
              <Tooltip title={t('dashboard.editInfo')}>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={openEditInfo}
                  style={{ paddingInline: 4 }}
                />
              </Tooltip>
            )}
          </Space>
        ),
        breadcrumb: {
          items: [{ title: t('dashboard.breadcrumb') }, { title: workspace.display_name }],
        },
      }}
    >

      <Tabs
        activeKey={activeTab}
        onChange={(k) => {
          // 同步 URL · 保留其它 query (deep link / 后退兼容)
          const next = new URLSearchParams(searchParams);
          if (k === 'overview') next.delete('tab');
          else next.set('tab', k);
          setSearchParams(next, { replace: true });
        }}
        items={[
          {
            key: 'overview',
            label: t('dashboard.tabs.overview'),
            children: (
              <OverviewPane
                workspace={workspace}
                snapshot={snapshot}
                quotaLoading={quotaLoading}
                quotaError={quotaError}
                fsxMounts={fsxMounts}
                s3Mounts={s3Mounts}
                isPlatformAdmin={isPlatformAdmin}
                onEditQuota={openEditQuota}
              />
            ),
          },
          {
            key: 'fsx',
            label: t('dashboard.tabs.fsx'),
            children: (
              <FsxTab
                wsId={wsId}
                isAdmin={canManage}
                isPlatformAdmin={isPlatformAdmin}
                primaryGid={
                  (workspace?.metadata_json?.primary_gid as number | undefined) ??
                  null
                }
              />
            ),
          },
          {
            key: 's3',
            label: t('dashboard.tabs.s3'),
            children: <S3Tab wsId={wsId} isAdmin={canManage} />,
          },
          {
            key: 'members',
            label: t('dashboard.tabs.members'),
            children: <MembersTab wsId={wsId} isAdmin={canManage} />,
          },
        ]}
      />

      {/* 编辑基本信息 Modal (展示名 + 描述) · admin only */}
      <Modal
        title={t('dashboard.editInfo')}
        open={editInfoOpen}
        afterOpenChange={fillInfoForm}
        onOk={() => void handleSaveInfo()}
        confirmLoading={savingInfo}
        onCancel={() => setEditInfoOpen(false)}
        okText={t('common:actions.save')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
      >
        <Form form={infoForm} layout="vertical" preserve={false}>
          <Form.Item
            name="display_name"
            label={t('dashboard.infoForm.displayName')}
            rules={[
              { required: true, message: t('dashboard.infoForm.displayNameRequired') },
              { max: 128, message: t('dashboard.infoForm.displayNameMax') },
            ]}
          >
            <Input placeholder={t('dashboard.infoForm.displayNamePlaceholder')} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t('dashboard.infoForm.descriptionLabel')}
            rules={[{ max: 200, message: t('dashboard.infoForm.descriptionMax') }]}
          >
            <Input.TextArea
              rows={3}
              maxLength={200}
              showCount
              placeholder={t('dashboard.infoForm.descriptionPlaceholder')}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 调整配额 Modal · admin only */}
      <Modal
        title={t('dashboard.adjustQuota')}
        open={editQuotaOpen}
        afterOpenChange={fillQuotaForm}
        onOk={() => void handleSaveQuota()}
        confirmLoading={savingQuota}
        onCancel={() => setEditQuotaOpen(false)}
        okText={t('common:actions.save')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
        width={680}
      >
        {/* 提示已合入 QuotaResourcePicker 顶部汇总条, 这里不再重复 */}
        <Form
          form={quotaForm}
          layout="vertical"
          preserve={false}
          initialValues={{ resources: quotaInitial }}
        >
          {/* 不传 clusterTag: ws.cluster_tag 是 ARN 末段 cluster-id 不是 ClusterName,
              picker 自动 fallback 到 listClusters()[0] (单集群部署唯一集群) */}
          <QuotaResourcePicker
            currentQuotaId={snapshot?.quota.computeQuotaId}
          />
        </Form>
      </Modal>
    </PageContainer>
  );
}

// ===== 概览 Tab 主体 =====

interface OverviewPaneProps {
  workspace: WorkspaceDetail;
  snapshot: WorkspaceQuotaSnapshot | null;
  quotaLoading: boolean;
  quotaError: string | null;
  fsxMounts: WorkspaceFsxMount[];
  s3Mounts: WorkspaceS3Mount[];
  isPlatformAdmin: boolean;  // 仅平台超管: 控制配额调整按钮 (ws 管理员不可改配额)
  onEditQuota: () => void;
}

function OverviewPane({
  workspace,
  snapshot,
  quotaLoading,
  quotaError,
  fsxMounts,
  s3Mounts,
  isPlatformAdmin,
  onEditQuota,
}: OverviewPaneProps) {
  const { t } = useTranslation(['workspace', 'common']);
  const statusLabel = (s: string): string =>
    Object.hasOwn(STATUS_LABEL_KEY, s) ? t(STATUS_LABEL_KEY[s as keyof typeof STATUS_LABEL_KEY]) : s;
  return (
    <>
      {/* 紧凑信息条: 状态 / 创建时间 / 集群 / Namespace / 成员 (描述+编辑已移到 PageContainer header) */}
      <Card
        size="small"
        bodyStyle={{ padding: '12px 16px' }}
        style={{ borderRadius: 8, marginBottom: 12 }}
      >
        <Row gutter={[28, 8]} align="middle" wrap>
          <Col flex="0 0 auto">
            <FieldRow
              label={t('common:fields.status')}
              value={
                <Badge
                  status={statusBadge(workspace.status)}
                  text={
                    <Text style={{ fontSize: 13, fontWeight: 500 }}>
                      {statusLabel(workspace.status)}
                    </Text>
                  }
                />
              }
            />
          </Col>
          <Col flex="0 0 auto">
            <FieldRow
              label={t('common:fields.createdAt')}
              value={
                <Tooltip title={dayjs(workspace.created_at).format('YYYY-MM-DD HH:mm:ss')}>
                  <Space size={4}>
                    <ClockCircleOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
                    <Text style={{ fontSize: 13 }}>
                      {dayjs(workspace.created_at).fromNow()}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      ({dayjs(workspace.created_at).format('YYYY-MM-DD HH:mm')})
                    </Text>
                  </Space>
                </Tooltip>
              }
            />
          </Col>
          <Col flex="0 0 auto">
            <FieldRow
              label={t('dashboard.fields.cluster')}
              value={
                <Space size={4}>
                  <ClusterOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
                  <Text style={{ fontSize: 13, fontWeight: 500 }}>
                    {workspace.cluster_tag}
                  </Text>
                </Space>
              }
            />
          </Col>
          <Col flex="0 0 auto">
            <FieldRow
              label="Namespace"
              value={
                <Tooltip title={workspace.namespace}>
                  <Text code style={{ fontSize: 12 }}>
                    {workspace.namespace}
                  </Text>
                </Tooltip>
              }
            />
          </Col>
          <Col flex="0 0 auto">
            <FieldRow
              label={t('dashboard.tabs.members')}
              value={
                <Space size={4}>
                  <TeamOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
                  <Text style={{ fontSize: 13, fontWeight: 500 }}>
                    {t('list.peopleCount', { count: workspace.member_count })}
                  </Text>
                </Space>
              }
            />
          </Col>
        </Row>
      </Card>

      {/* 配额使用 (真后端) */}
      <WorkspaceQuotaBlock
        snapshot={snapshot}
        loading={quotaLoading}
        error={quotaError}
        isPlatformAdmin={isPlatformAdmin}
        onEditQuota={onEditQuota}
      />

      {/* GPU 利用率/占用卡数图 · 仅 ws 管理员/超管可见 (组件内 useIsWsAdmin 判定, 非管理员不渲染) */}
      <WorkspaceGpuUtilChart wsId={workspace.id} />

      {/* 已挂载存储 (从 workspace.metadata_json 派生, 跟 ws 一起 loaded) */}
      <MountSummaryCard fsxMounts={fsxMounts} s3Mounts={s3Mounts} />
    </>
  );
}

/** 紧凑信息条用的 label/value 行: label 上方小灰字, value 下方主字 */
function FieldRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ lineHeight: 1.3 }}>
      <Text type="secondary" style={{ fontSize: 11, letterSpacing: 0.4 }}>
        {label}
      </Text>
      <div style={{ fontSize: 13 }}>{value}</div>
    </div>
  );
}

// ===== 已挂载存储卡 =====

interface MountSummaryCardProps {
  fsxMounts: WorkspaceFsxMount[];
  s3Mounts: WorkspaceS3Mount[];
}

function MountSummaryCard({
  fsxMounts,
  s3Mounts,
}: MountSummaryCardProps) {
  const { t } = useTranslation(['workspace']);
  // FSx + S3 横排两栏, 节省垂直空间; 每条挂载单行紧凑显示
  return (
    <Card
      size="small"
      title={
        <Space size={6}>
          <DatabaseOutlined style={{ color: 'rgba(0,0,0,0.55)' }} />
          <span style={{ fontSize: 13 }}>{t('dashboard.mounts.title')}</span>
          <Text type="secondary" style={{ fontSize: 12 }}>
            FSx {fsxMounts.length} · S3 {s3Mounts.length}
          </Text>
        </Space>
      }
      style={{ borderRadius: 8, marginTop: 12 }}
      bodyStyle={{ padding: 12 }}
      headStyle={{ padding: '0 12px', minHeight: 36 }}
    >
      <Row gutter={[12, 8]}>
        <Col xs={24} md={12}>
          <MountColumn
            kind="FSx Lustre"
            color="#13c2c2"
            emptyHint={t('dashboard.mounts.emptyFsx')}
            items={fsxMounts.map((m) => ({
              key: m.mount_id || `${m.filesystem_id}::${m.subdir ?? ''}`,
              mountId: m.mount_id,
              mountPath: m.mount_path,
              source: `${m.filesystem_id}${m.subdir ? ` / ${m.subdir}` : ''}`,
              description: m.description,
            }))}
          />
        </Col>
        <Col xs={24} md={12}>
          <MountColumn
            kind="S3 Bucket"
            color="#fa8c16"
            emptyHint={t('dashboard.mounts.emptyS3')}
            items={s3Mounts.map((m) => ({
              key: m.mount_id || `${m.bucket_name}::${m.prefix ?? ''}`,
              mountId: m.mount_id,
              mountPath: m.mount_path,
              source: `${m.bucket_name}${m.prefix ? ` / ${m.prefix}` : ''}`,
              description: m.description,
            }))}
          />
        </Col>
      </Row>
    </Card>
  );
}

interface MountItem {
  key: string;
  mountId?: string | null;
  mountPath: string;
  source: string;
  description?: string | null;
}

function MountColumn({
  kind,
  color,
  items,
  emptyHint,
}: {
  kind: string;
  color: string;
  items: MountItem[];
  emptyHint: string;
}) {
  const { t } = useTranslation(['workspace']);
  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 6,
          paddingLeft: 6,
          borderLeft: `3px solid ${color}`,
        }}
      >
        <Text strong style={{ fontSize: 13 }}>
          {kind}
        </Text>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('dashboard.mounts.count', { count: items.length })}
        </Text>
      </div>
      {items.length === 0 ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {emptyHint}
        </Text>
      ) : (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {items.map((m) => (
            <div key={m.key} style={{ fontSize: 12, lineHeight: 1.5 }}>
              {m.mountId && (
                <Text strong style={{ fontFamily: 'monospace', marginRight: 6 }}>
                  {m.mountId}
                </Text>
              )}
              <Text code style={{ fontSize: 12 }}>
                {m.mountPath}
              </Text>
              <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                → {m.source}
              </Text>
              {m.description && (
                <Text
                  type="secondary"
                  style={{ fontSize: 12, display: 'block' }}
                >
                  {m.description}
                </Text>
              )}
            </div>
          ))}
        </Space>
      )}
    </div>
  );
}

// ===== 配额使用 (跟之前一致, 真后端) =====

interface WorkspaceQuotaBlockProps {
  snapshot: WorkspaceQuotaSnapshot | null;
  loading: boolean;
  error: string | null;
  // 仅平台超管 — 配额调整属平台级资源分配, ws 管理员不可改 (否则可私自给自己 ws 加资源)。
  // 区别于 ws 内其它管理操作 (编辑信息/成员/挂载) 走 canManage。
  isPlatformAdmin: boolean;
  onEditQuota: () => void;
}

function WorkspaceQuotaBlock({
  snapshot,
  loading,
  error,
  isPlatformAdmin,
  onEditQuota,
}: WorkspaceQuotaBlockProps) {
  const { t } = useTranslation(['workspace', 'common']);
  const { token } = theme.useToken();

  // 资源池机型过多时折叠, 点"显示全部"弹框列该池全部机型 (null = 不开)
  const [poolModal, setPoolModal] = useState<{
    title: string;
    items: ComputeQuotaResource[];
    accent: string;
  } | null>(null);

  // 「调整配额」按钮 · 仅平台超管 (后端 quota patch/create/delete 亦 require_admin)
  const editExtra = isPlatformAdmin ? (
    <Button
      type="link"
      size="small"
      icon={<EditOutlined />}
      onClick={onEditQuota}
    >
      {t('dashboard.adjustQuota')}
    </Button>
  ) : undefined;

  if (loading) {
    return (
      <Card
        title={t('dashboard.quota.title')}
        extra={editExtra}
        style={{ borderRadius: 12, marginBottom: 16 }}
      >
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
    );
  }

  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('dashboard.quota.apiUnavailable')}
        description={error}
      />
    );
  }

  if (!snapshot || snapshot.quota.resources.length === 0) {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('dashboard.quota.notAssigned')}
      />
    );
  }

  const { quota, usage } = snapshot;
  const hasUsage = usage !== null;

  const totals = aggregateQuota(quota.resources);
  const gpuQuota = totals.totalAccelerators;
  const cpuCores = totals.totalVCpu;
  const memGib = totals.totalMemoryInGiB;

  const gpuUsed = usage?.totals.accelerators ?? 0;
  const cpuUsed = usage?.totals.vCpu ?? 0;
  const memUsed = usage?.totals.memoryInGiB ?? 0;

  const pctOf = (used: number, total: number): number =>
    total === 0 ? 0 : Math.round((used / total) * 100);
  const gpuPct = pctOf(gpuUsed, gpuQuota);
  const cpuPct = pctOf(cpuUsed, cpuCores);
  const memPct = pctOf(memUsed, memGib);

  const colorFor = (pct: number): string => {
    if (pct >= 90) return token.colorError;
    if (pct >= 70) return token.colorWarning;
    return token.colorSuccess;
  };

  const fmt = (n: number): string =>
    Number.isInteger(n) ? String(n) : n.toFixed(1);

  // 按资源池分两组 · 缺 pool 字段的项兜底归 CPU 池
  const gpuResources = quota.resources.filter((r) => r.pool === 'gpu');
  const cpuResources = quota.resources.filter((r) => r.pool !== 'gpu');

  // 资源池机型行 (清单式, 替代每机型一张大卡)
  const renderPoolList = (items: ComputeQuotaResource[], accent: string) => {
    if (items.length === 0) {
      return (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('dashboard.quota.noResources')}
        </Text>
      );
    }
    const preview = items.slice(0, POOL_PREVIEW_MAX);
    return (
      <>
        {preview.map((r) => {
          const gpuType = r.gpuType ?? null;
          return (
            <div
              key={r.instanceType}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                padding: '6px 0',
                borderBottom: '1px dashed rgba(5,5,5,0.06)',
              }}
            >
              <span>
                <Text style={{ fontSize: 13, fontFamily: 'monospace' }}>
                  {r.instanceType}
                </Text>
                {gpuType && (
                  <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                    · {gpuType}
                  </Text>
                )}
              </span>
              <span
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: accent,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {r.count}
                <Text type="secondary" style={{ fontSize: 11, fontWeight: 400, marginLeft: 4 }}>
                  {t('dashboard.pool.instanceUnit', { count: r.count })}
                </Text>
              </span>
            </div>
          );
        })}
        {items.length > POOL_PREVIEW_MAX && (
          <Button
            type="link"
            size="small"
            style={{ paddingInline: 0, marginTop: 4 }}
            onClick={() =>
              setPoolModal({
                title: items === gpuResources ? t('dashboard.pool.gpu') : t('dashboard.pool.cpu'),
                items,
                accent,
              })
            }
          >
            {t('dashboard.pool.showAll', { count: items.length })}
          </Button>
        )}
      </>
    );
  };

  // 资源池块 (标题 + 机型清单), 紧凑型, 高度 ~POOL_PREVIEW_MAX × 28px
  const renderPoolBlock = (
    title: string,
    items: ComputeQuotaResource[],
    accent: string,
    icon: ReactNode,
  ) => (
    <Col xs={24} md={12}>
      <div
        style={{
          border: `1px solid ${token.colorBorderSecondary}`,
          borderRadius: 8,
          height: '100%',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            borderLeft: `3px solid ${accent}`,
            borderTopLeftRadius: 5,
            borderBottomLeftRadius: 0,
          }}
        >
          <Space size={6}>
            <span style={{ color: accent, fontSize: 14, display: 'flex' }}>
              {icon}
            </span>
            <Text strong style={{ fontSize: 13 }}>
              {title}
            </Text>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('dashboard.pool.typeCount', { count: items.length })}
          </Text>
        </div>
        <div style={{ padding: '4px 12px 8px' }}>
          {renderPoolList(items, accent)}
        </div>
      </div>
    </Col>
  );

  // 紧凑用量行: 一张卡里 GPU/CPU/内存 横排, 数字 + Progress + 占比 同行
  const renderUsageRow = (
    label: string,
    used: number,
    total: number,
    unit: string,
    pct: number,
  ) => (
    <Col xs={24} sm={8}>
      <div style={{ padding: '6px 4px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <Text type="secondary" style={{ fontSize: 11, letterSpacing: 0.4 }}>
            {label}
          </Text>
          <span style={{ fontVariantNumeric: 'tabular-nums', fontSize: 13 }}>
            {hasUsage ? (
              <>
                <Text strong style={{ fontSize: 14 }}>
                  {fmt(used)}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {' '}/ {fmt(total)} {unit}
                </Text>
                <Text
                  style={{
                    fontSize: 12,
                    marginLeft: 6,
                    color: colorFor(pct),
                    fontWeight: 500,
                  }}
                >
                  {pct}%
                </Text>
              </>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {fmt(total)} {unit} {t('dashboard.quota.collecting')}
              </Text>
            )}
          </span>
        </div>
        <Progress
          percent={hasUsage ? Math.max(0, Math.min(100, pct)) : 0}
          strokeColor={hasUsage ? colorFor(pct) : token.colorBorderSecondary}
          showInfo={false}
          size="small"
          style={{ marginTop: 2 }}
        />
      </div>
    </Col>
  );

  return (
    <>
    <Card
      size="small"
      title={<span style={{ fontSize: 13 }}>{t('dashboard.quota.title')}</span>}
      extra={editExtra}
      style={{ borderRadius: 8, marginBottom: 12 }}
      bodyStyle={{ padding: 12 }}
      headStyle={{ padding: '0 12px', minHeight: 36 }}
    >
      {/* 用量条 (紧凑) · 三列横排, 替代之前 3 张大 Card */}
      <Row gutter={[16, 0]} style={{ marginBottom: 8 }}>
        {renderUsageRow('GPU', gpuUsed, gpuQuota, t('dashboard.quota.cardsUnit', { count: gpuQuota }), gpuPct)}
        {renderUsageRow('CPU', cpuUsed, cpuCores, t('dashboard.quota.coresUnit', { count: cpuCores }), cpuPct)}
        {renderUsageRow(t('dashboard.quota.memory'), memUsed, memGib, 'GiB', memPct)}
      </Row>

      {/* 已分配资源池 · GPU / CPU 横排 · 清单式 */}
      <Row gutter={[12, 12]} style={{ marginTop: 4 }}>
        {renderPoolBlock(
          t('dashboard.pool.gpu'),
          gpuResources,
          token.colorPrimary,
          <ThunderboltOutlined />,
        )}
        {renderPoolBlock(
          t('dashboard.pool.cpu'),
          cpuResources,
          token.colorSuccess,
          <DesktopOutlined />,
        )}
      </Row>
    </Card>

    {/* 显示全部机型弹框 · 列出该池所有机型和数量 (清单式, 不再用大卡) */}
    <Modal
      open={poolModal !== null}
      title={
        poolModal
          ? t('dashboard.pool.modalTitle', {
              title: poolModal.title,
              count: poolModal.items.length,
            })
          : ''
      }
      footer={null}
      onCancel={() => setPoolModal(null)}
      width={520}
    >
      {poolModal && (
        <div style={{ marginTop: 8 }}>
          {poolModal.items.map((r) => {
            const gpuType = r.gpuType ?? null;
            return (
              <div
                key={r.instanceType}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'baseline',
                  padding: '8px 0',
                  borderBottom: '1px dashed rgba(5,5,5,0.06)',
                }}
              >
                <span>
                  <Text style={{ fontSize: 13, fontFamily: 'monospace' }}>
                    {r.instanceType}
                  </Text>
                  {gpuType && (
                    <Text type="secondary" style={{ fontSize: 12, marginLeft: 6 }}>
                      · {gpuType}
                    </Text>
                  )}
                </span>
                <span
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: poolModal.accent,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {r.count}
                  <Text type="secondary" style={{ fontSize: 11, fontWeight: 400, marginLeft: 4 }}>
                    {t('dashboard.pool.instanceUnit', { count: r.count })}
                  </Text>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
    </>
  );
}
