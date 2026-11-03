import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Result,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
  theme,
} from 'antd';
import { PageContainer, StatisticCard } from '@ant-design/pro-components';
import {
  ApartmentOutlined,
  CloudServerOutlined,
  ClusterOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  getClusterSummary,
  listInstanceGroups,
  syncCluster,
  type AdvancedFeatureDetail,
  type ClusterSummary,
  type SyncStatus,
} from '../api/cluster';
import {
  aggregateQuota,
  createComputeQuota,
  deleteComputeQuota,
  getWorkspaceQuotaUsage,
  listClusterQuotas,
  updateComputeQuota,
  type ClusterQuotaList,
  type ComputeQuota,
  type ComputeQuotaResource,
  type CreateComputeQuotaPayload,
  type PreemptTeamTasks,
  type QuotaUsage,
  type ResourceSharingStrategy,
  type UpdateComputeQuotaPayload,
} from '../api/quota';
import { ApiError } from '@/shared/api';
import { listWorkspaces, type Workspace } from '@/features/workspace/api';
import { SEMANTIC_COLORS } from '@/shared/ui/metrics/chartTheme';

const { Text } = Typography;

// Prototype currently targets a single cluster. Swap for a selector when multi-cluster lands.
const DEFAULT_CLUSTER_TAG = 'hp-cluster-hypd-0507-9390';

/** Map backend cluster state → AntD Badge status. */
function stateBadgeStatus(state: string): 'success' | 'processing' | 'error' | 'warning' | 'default' {
  switch (state) {
    case 'InService':
      return 'success';
    case 'Creating':
    case 'Updating':
      return 'processing';
    case 'Failed':
      return 'error';
    case 'Deleting':
      return 'warning';
    default:
      return 'default';
  }
}

/** sync_status → Tag color. */
function syncTagColor(sync: SyncStatus): string {
  switch (sync) {
    case 'in_sync':
      return 'green';
    case 'out_of_sync':
      return 'orange';
    case 'aws_unavailable':
      return 'red';
    default:
      return 'default';
  }
}

function syncLabel(sync: SyncStatus): string {
  switch (sync) {
    case 'in_sync':
      return '已同步';
    case 'out_of_sync':
      return '未同步';
    case 'aws_unavailable':
      return 'AWS 不可达';
    default:
      return String(sync);
  }
}

/** Normalize an advanced feature value into { enabled, version, label }. */
function renderAdvancedFeature(key: string, value: unknown): {
  color: string;
  label: string;
} {
  if (value && typeof value === 'object') {
    const detail = value as AdvancedFeatureDetail;
    const enabled = Boolean(detail.enabled);
    const version = detail.version ? String(detail.version) : null;
    return {
      color: enabled ? 'green' : 'default',
      label: enabled ? `${key} · ${version ?? 'on'}` : `${key} · off`,
    };
  }
  // Legacy primitive fallback.
  const enabled = value === true || value === 'enabled' || value === 'Enabled';
  const disabled = value === false || value === 'disabled' || value === null;
  return {
    color: enabled ? 'green' : disabled ? 'default' : 'blue',
    label:
      typeof value === 'boolean'
        ? `${key} · ${enabled ? 'on' : 'off'}`
        : `${key} · ${String(value)}`,
  };
}

/**
 * Flattened row for the Compute Quota table. AWS `ComputeQuota` holds a list
 * of resources (one per instance-type); we expand each into its own row so the
 * table reads left-to-right "team · instance-type · capacity". The parent quota
 * handle is preserved so edit/delete can target it directly.
 */
interface QuotaMatrixRow {
  key: string; // `${computeQuotaId}::${instanceType}`
  computeQuotaId: string;
  computeQuotaArn: string;
  teamName: string;
  workspaceId: string | null; // resolved from workspaces[] by teamName; null if no mapping
  workspaceDisplayName: string; // falls back to teamName
  resource: ComputeQuotaResource;
  parent: ComputeQuota; // full parent for edit-drawer context
}

/** Edit drawer form: one row of the resource array + team-level knobs. */
interface QuotaEditFormValues {
  // Resource-level
  count: number;
  accelerators: number;
  // Team-level
  fairShareWeight: number;
  sharingStrategy: ResourceSharingStrategy;
  borrowLimit?: number;
  preemptTeamTasks: PreemptTeamTasks;
  activationState: 'Enabled' | 'Disabled';
  description?: string;
}

/**
 * Create-quota modal form values — creates a new ComputeQuota (single resource row).
 *
 * `workspaceId` drives the API call (POST /workspaces/{wsId}/quota) and
 * `workspaceName` becomes the AWS `target.teamName` — we keep both on the form
 * so the user selects a workspace once and we resolve both fields from the
 * same source of truth.
 */
interface QuotaCreateFormValues {
  workspaceId: string;
  workspaceName: string;
  description?: string;
  instanceType: string;
  count: number;
  accelerators: number;
  fairShareWeight: number;
  sharingStrategy: ResourceSharingStrategy;
  borrowLimit?: number;
  preemptTeamTasks: PreemptTeamTasks;
  activationState: 'Enabled' | 'Disabled';
}

export default function AdminCluster() {
  const { token } = theme.useToken();
  const [summary, setSummary] = useState<ClusterSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingSync, setLoadingSync] = useState(false);
  const [error, setError] = useState<{ status?: number; message: string } | null>(null);

  // Quota state is independent from summary so a quota-API outage does not
  // break the rest of the page.
  const [quotaList, setQuotaList] = useState<ClusterQuotaList | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(true);
  const [quotaError, setQuotaError] = useState<string | null>(null);
  // Per-workspace usage map (teamName → QuotaUsage). null when endpoint unavailable.
  const [usageMap, setUsageMap] = useState<Record<string, QuotaUsage | null>>({});

  // Edit drawer state.
  const [editTarget, setEditTarget] = useState<QuotaMatrixRow | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [editForm] = Form.useForm<QuotaEditFormValues>();

  // Create modal state + workspace list (for the ws dropdown).
  const [createOpen, setCreateOpen] = useState(false);
  const [clusterInstanceTypes, setClusterInstanceTypes] = useState<
    { instance_type: string; gpu_type: string | null }[]
  >([]);
  const [instanceTypesLoading, setInstanceTypesLoading] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createForm] = Form.useForm<QuotaCreateFormValues>();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);

  // Per-row delete-in-flight flag → suppress double click.
  const [deletingKey, setDeletingKey] = useState<string | null>(null);

  const fetchSummary = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getClusterSummary(DEFAULT_CLUSTER_TAG);
      if (signal?.aborted) return;
      setSummary(data);
      setError(null);
    } catch (err: unknown) {
      if (signal?.aborted) return;
      if (err instanceof ApiError) {
        setError({ status: err.status, message: err.message });
      } else if (err instanceof Error) {
        setError({ message: err.message });
      } else {
        setError({ message: String(err) });
      }
    }
  }, []);

  const fetchQuotas = useCallback(
    async (signal?: AbortSignal, knownWorkspaces?: Workspace[]) => {
      try {
        setQuotaLoading(true);
        const data = await listClusterQuotas(DEFAULT_CLUSTER_TAG);
        if (signal?.aborted) return;
        setQuotaList(data);
        setQuotaError(null);

        // Usage is optional — fetch per-workspace and tolerate individual
        // failures. Resolve teamName → workspace.id via the workspaces list.
        // We use the incoming snapshot (`knownWorkspaces`) on first load
        // because React state hasn't settled yet; otherwise use state.
        const wsList = knownWorkspaces ?? workspaces;
        const nameToId = new Map<string, string>(
          wsList.map((w) => [w.name, w.id]),
        );
        const teamNames = Array.from(
          new Set(data.quotas.map((q) => q.target.teamName)),
        );
        const usagePairs = await Promise.all(
          teamNames.map(async (name): Promise<[string, QuotaUsage | null]> => {
            const wsId = nameToId.get(name);
            if (!wsId) return [name, null];
            try {
              return [name, await getWorkspaceQuotaUsage(wsId)];
            } catch {
              return [name, null];
            }
          }),
        );
        if (signal?.aborted) return;
        setUsageMap(Object.fromEntries(usagePairs));
      } catch (err: unknown) {
        if (signal?.aborted) return;
        const msg =
          err instanceof ApiError
            ? `${err.status} ${err.message}`
            : err instanceof Error
              ? err.message
              : String(err);
        setQuotaError(msg);
      } finally {
        if (!signal?.aborted) setQuotaLoading(false);
      }
    },
    [workspaces],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchSummary(controller.signal).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    // Load workspaces first so fetchQuotas has the teamName → id map ready
    // on initial render. Usage resolution falls back to null when the
    // workspace list fails.
    listWorkspaces()
      .then((list) => {
        if (controller.signal.aborted) return;
        setWorkspaces(list);
        void fetchQuotas(controller.signal, list);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          void fetchQuotas(controller.signal, []);
        }
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchSummary]);

  // 打开"新增配额"弹框时按当前集群实际机型填下拉 (去重 + 附 GPU 型号)。
  useEffect(() => {
    if (!createOpen) return;
    let cancelled = false;
    setInstanceTypesLoading(true);
    (async () => {
      try {
        const igs = await listInstanceGroups(DEFAULT_CLUSTER_TAG);
        if (cancelled) return;
        const seen = new Set<string>();
        const list: { instance_type: string; gpu_type: string | null }[] = [];
        for (const ig of igs) {
          if (!ig.InstanceType || seen.has(ig.InstanceType)) continue;
          seen.add(ig.InstanceType);
          list.push({ instance_type: ig.InstanceType, gpu_type: ig.gpu_type ?? null });
        }
        setClusterInstanceTypes(list);
      } catch {
        if (!cancelled) {
          setClusterInstanceTypes([]);
          message.error('加载集群机型失败,请重试');
        }
      } finally {
        if (!cancelled) setInstanceTypesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [createOpen]);

  const handleSync = useCallback(async () => {
    setLoadingSync(true);
    try {
      const result = await syncCluster(DEFAULT_CLUSTER_TAG);
      message.success(
        `同步完成: IG +${result.instance_groups.upserted} / Node +${result.nodes.upserted}`,
      );
      await fetchSummary();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(msg);
    } finally {
      setLoadingSync(false);
    }
  }, [fetchSummary]);

  const healthPct = useMemo(() => {
    if (!summary || summary.health.total === 0) return 0;
    return Math.round((summary.health.ready / summary.health.total) * 100);
  }, [summary]);

  // Expand ComputeQuota[] × resources[] into flat table rows.
  // Key is `${computeQuotaId}::${instanceType}` so row actions (edit/delete)
  // can reach the parent quota. Multiple resources on the same quota share
  // the same parent.
  const quotaRows = useMemo<QuotaMatrixRow[]>(() => {
    if (!quotaList) return [];
    const nameToWs = new Map<string, Workspace>(
      workspaces.map((w) => [w.name, w]),
    );
    const rows: QuotaMatrixRow[] = [];
    for (const q of quotaList.quotas) {
      const ws = nameToWs.get(q.target.teamName) ?? null;
      for (const r of q.resources) {
        rows.push({
          key: `${q.computeQuotaId}::${r.instanceType}`,
          computeQuotaId: q.computeQuotaId,
          computeQuotaArn: q.computeQuotaArn,
          teamName: q.target.teamName,
          workspaceId: ws?.id ?? null,
          workspaceDisplayName: ws?.display_name ?? q.target.teamName,
          resource: r,
          parent: q,
        });
      }
    }
    return rows;
  }, [quotaList, workspaces]);

  // Grand totals derived on the FE because AWS doesn't pre-aggregate.
  const grandTotals = useMemo(() => {
    if (!quotaList) return null;
    let gpuQuota = 0;
    let gpuUsed = 0;
    let hasAnyUsage = false;
    for (const q of quotaList.quotas) {
      gpuQuota += aggregateQuota(q.resources).totalAccelerators;
      const u = usageMap[q.target.teamName];
      if (u) {
        hasAnyUsage = true;
        gpuUsed += u.totals.accelerators;
      }
    }
    const pct = gpuQuota > 0 && hasAnyUsage ? (gpuUsed / gpuQuota) * 100 : 0;
    return { gpuQuota, gpuUsed, pct, hasAnyUsage };
  }, [quotaList, usageMap]);

  const openEditDrawer = useCallback(
    (row: QuotaMatrixRow) => {
      setEditTarget(row);
      editForm.setFieldsValue({
        count: row.resource.count,
        accelerators: row.resource.accelerators,
        fairShareWeight: row.parent.target.fairShareWeight,
        sharingStrategy: row.parent.sharingConfig.strategy,
        borrowLimit: row.parent.sharingConfig.borrowLimit ?? undefined,
        preemptTeamTasks: row.parent.preemptTeamTasks,
        activationState: row.parent.activationState,
        description: row.parent.description ?? undefined,
      });
    },
    [editForm],
  );

  const closeEditDrawer = useCallback(() => {
    setEditTarget(null);
    editForm.resetFields();
  }, [editForm]);

  const openCreateModal = useCallback(() => {
    createForm.resetFields();
    createForm.setFieldsValue({
      count: 1,
      accelerators: 0,
      fairShareWeight: 50,
      sharingStrategy: 'LendAndBorrow',
      borrowLimit: 50,
      preemptTeamTasks: 'LowerPriority',
      activationState: 'Enabled',
    });
    setCreateOpen(true);
  }, [createForm]);

  const closeCreateModal = useCallback(() => {
    setCreateOpen(false);
    createForm.resetFields();
  }, [createForm]);

  const handleCreateSave = useCallback(async () => {
    try {
      const values = await createForm.validateFields();
      // Resolve workspaceId from the selected workspace name; the Select stores
      // id as value but we also need the name for AWS `target.teamName`.
      const ws = workspaces.find((w) => w.id === values.workspaceId);
      if (!ws) {
        message.error('找不到所选工作空间,请刷新页面');
        return;
      }
      setCreateSaving(true);
      // Backend derives ClusterArn from workspace.cluster; do NOT send it here.
      const payload: CreateComputeQuotaPayload = {
        name: ws.name,
        description: values.description,
        activationState: values.activationState,
        resources: [
          {
            instanceType: values.instanceType,
            count: values.count,
            accelerators: values.accelerators,
          },
        ],
        sharingConfig: {
          strategy: values.sharingStrategy,
          borrowLimit:
            values.sharingStrategy === 'LendAndBorrow'
              ? (values.borrowLimit ?? null)
              : null,
        },
        preemptTeamTasks: values.preemptTeamTasks,
        target: {
          teamName: ws.name,
          fairShareWeight: values.fairShareWeight,
        },
      };
      await createComputeQuota(ws.id, payload);
      message.success('配额已创建');
      closeCreateModal();
      await fetchQuotas();
    } catch (err: unknown) {
      // AntD form validation rejections carry `errorFields` — ignore those
      // because AntD already highlights the offending field in-place.
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`创建失败: ${msg}`);
    } finally {
      setCreateSaving(false);
    }
  }, [createForm, closeCreateModal, fetchQuotas, workspaces]);

  const handleDelete = useCallback(
    async (row: QuotaMatrixRow) => {
      // Deletion is a workspace-scoped endpoint; we can't call it for orphan
      // quotas whose teamName doesn't map to any workspace row.
      if (!row.workspaceId) {
        message.error(
          `无法删除: team ${row.teamName} 未绑定到工作空间,请先在 DB 中建立关联`,
        );
        return;
      }
      setDeletingKey(row.key);
      try {
        await deleteComputeQuota(row.workspaceId);
        message.success('配额已删除');
        await fetchQuotas();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        message.error(`删除失败: ${msg}`);
      } finally {
        setDeletingKey(null);
      }
    },
    [fetchQuotas],
  );

  const handleEditSave = useCallback(async () => {
    if (!editTarget) return;
    // Edit/PATCH also targets the workspace route; guard against orphan rows.
    if (!editTarget.workspaceId) {
      message.error(
        `无法保存: team ${editTarget.teamName} 未绑定到工作空间,请先在 DB 中建立关联`,
      );
      return;
    }
    try {
      const values = await editForm.validateFields();
      setEditSaving(true);

      // Build patch: only send fields that actually changed. For `resources`
      // we always send the full array because AWS overwrites it wholesale —
      // a partial patch would silently drop the sibling rows.
      const payload: UpdateComputeQuotaPayload = {};
      const orig = editTarget.parent;

      // Replace the matching resource row; keep siblings untouched.
      const updatedResources = orig.resources.map((r) =>
        r.instanceType === editTarget.resource.instanceType
          ? {
              instanceType: r.instanceType,
              count: values.count,
              accelerators: values.accelerators,
            }
          : {
              instanceType: r.instanceType,
              count: r.count,
              accelerators: r.accelerators,
            },
      );
      const resourceChanged =
        values.count !== editTarget.resource.count ||
        values.accelerators !== editTarget.resource.accelerators;
      if (resourceChanged) payload.resources = updatedResources;

      if (values.activationState !== orig.activationState) {
        payload.activationState = values.activationState;
      }
      if ((values.description ?? '') !== (orig.description ?? '')) {
        payload.description = values.description;
      }
      if (values.preemptTeamTasks !== orig.preemptTeamTasks) {
        payload.preemptTeamTasks = values.preemptTeamTasks;
      }
      if (
        values.sharingStrategy !== orig.sharingConfig.strategy ||
        values.borrowLimit !== (orig.sharingConfig.borrowLimit ?? undefined)
      ) {
        payload.sharingConfig = {
          strategy: values.sharingStrategy,
          borrowLimit:
            values.sharingStrategy === 'LendAndBorrow'
              ? (values.borrowLimit ?? null)
              : null,
        };
      }
      if (values.fairShareWeight !== orig.target.fairShareWeight) {
        payload.target = {
          teamName: orig.target.teamName,
          fairShareWeight: values.fairShareWeight,
        };
      }

      if (Object.keys(payload).length === 0) {
        message.info('没有更改');
        closeEditDrawer();
        return;
      }
      // workspaceId null-guard happened at function entry, so the non-null
      // assertion below is safe.
      await updateComputeQuota(editTarget.workspaceId as string, payload);
      message.success('配额已更新');
      closeEditDrawer();
      await fetchQuotas();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`保存失败: ${msg}`);
    } finally {
      setEditSaving(false);
    }
  }, [editTarget, editForm, fetchQuotas, closeEditDrawer]);

  if (loading) {
    return (
      <PageContainer title="集群管理" subTitle="HyperPod Cluster 实时视图">
        <Card style={{ borderRadius: 12, minHeight: 320 }}>
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 280, flexDirection: 'column', gap: 12 }}>
            <Spin size="large" />
            <div style={{ color: '#999', fontSize: 13 }}>加载集群数据...</div>
          </div>
        </Card>
      </PageContainer>
    );
  }

  if (error || !summary) {
    const isNetwork = !error?.status;
    return (
      <PageContainer title="集群管理">
        <Result
          status="error"
          title={isNetwork ? 'API 未启动' : `API 请求失败 (${error?.status})`}
          subTitle={
            isNetwork
              ? '请启动后端 localhost:8000（uvicorn platform_api.main:app）'
              : error?.message
          }
        />
      </PageContainer>
    );
  }

  const { cluster, instance_groups_db, instance_groups_live, nodes_db_count, nodes_live_count, health, advanced_features, sync_status, errors } = summary;

  const lastSyncedText = cluster.last_synced_at
    ? dayjs(cluster.last_synced_at).format('YYYY-MM-DD HH:mm:ss')
    : '从未同步';

  return (
    <PageContainer
      title="集群管理"
      subTitle={`HyperPod Cluster · ${cluster.cluster_tag}`}
      extra={[
        <Button
          key="sync"
          type="primary"
          icon={<SyncOutlined spin={loadingSync} />}
          loading={loadingSync}
          onClick={handleSync}
        >
          同步真实数据
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon={false}
        banner
        style={{ marginBottom: 12, borderRadius: 8 }}
        message={
          <Text type="secondary" style={{ fontSize: 12 }}>
            最近同步: {lastSyncedText} · 点击右上角「同步真实数据」从 AWS + K8s 拉最新状态
          </Text>
        }
      />

      {errors && errors.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16, borderRadius: 12 }}
          message="同步过程中发生错误"
          description={
            <ul style={{ margin: 0, paddingInlineStart: 20 }}>
              {errors.map((e, i) => (
                <li key={i}>
                  <Text type="secondary">{e}</Text>
                </li>
              ))}
            </ul>
          }
        />
      )}

      {/* Cluster header */}
      <Card style={{ borderRadius: 12, marginBottom: 16 }}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} md={10}>
            <Space direction="vertical" size={4}>
              <Space size={12}>
                <ClusterOutlined style={{ fontSize: 22, color: token.colorPrimary }} />
                <Typography.Title level={4} style={{ margin: 0 }}>
                  {cluster.cluster_tag}
                </Typography.Title>
                <Badge
                  status={stateBadgeStatus(cluster.state)}
                  text={cluster.state}
                />
              </Space>
              <Text type="secondary">{cluster.id}</Text>
            </Space>
          </Col>
          <Col xs={24} md={14}>
            <Descriptions size="small" column={2}>
              <Descriptions.Item label="类型">
                <Tag color="purple">{cluster.type}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Region">
                <Tag color="geekblue">{cluster.region}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Workspace Scope">
                <Tag color={cluster.workspace_scope === 'shared' ? 'blue' : 'gold'}>
                  {cluster.workspace_scope}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="最近同步">
                {cluster.last_synced_at
                  ? dayjs(cluster.last_synced_at).format('YYYY-MM-DD HH:mm:ss')
                  : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {dayjs(cluster.created_at).format('YYYY-MM-DD HH:mm')}
              </Descriptions.Item>
              <Descriptions.Item label="同步状态">
                <Tag icon={<SyncOutlined />} color={syncTagColor(sync_status)}>
                  {syncLabel(sync_status)}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Col>
        </Row>
      </Card>

      {/* KPI row: nodes DB vs Live vs Health */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <StatisticCard
            statistic={{
              title: 'Instance Groups (DB)',
              value: instance_groups_db.length,
              suffix: '组',
              icon: <ApartmentOutlined style={{ color: token.colorPrimary }} />,
            }}
            chart={
              <Text type="secondary" style={{ fontSize: 12 }}>
                Live 实际 {instance_groups_live.length} 组
              </Text>
            }
            chartPlacement="bottom"
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <StatisticCard
            statistic={{
              title: '节点 (DB)',
              value: nodes_db_count,
              suffix: '台',
              icon: <CloudServerOutlined style={{ color: SEMANTIC_COLORS.gpu }} />,
            }}
            chart={
              <Text type="secondary" style={{ fontSize: 12 }}>
                Live K8s 上报 {nodes_live_count} 台
              </Text>
            }
            chartPlacement="bottom"
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <StatisticCard
            statistic={{
              title: '节点健康率',
              value: healthPct,
              suffix: '%',
              valueStyle: { color: token.colorSuccess },
            }}
            chart={
              <Progress
                percent={healthPct}
                strokeColor={token.colorSuccess}
                showInfo={false}
                size="small"
              />
            }
            chartPlacement="bottom"
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <StatisticCard
            statistic={{
              title: '配额池',
              value: quotaRows.length,
              suffix: '个',
              icon: <ThunderboltOutlined style={{ color: token.colorWarning }} />,
            }}
          />
        </Col>
      </Row>

      {/* Instance groups DB vs Live */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={12}>
          <Card
            title={
              <Space>
                <ApartmentOutlined />
                Instance Groups · DB ({instance_groups_db.length})
              </Space>
            }
            style={{ borderRadius: 12 }}
          >
            <Table
              rowKey={(r) => r.group_name}
              size="small"
              pagination={false}
              dataSource={instance_groups_db}
              locale={{ emptyText: '暂无数据' }}
              columns={[
                {
                  title: '名称',
                  dataIndex: 'group_name',
                  render: (v: string) => <Text strong>{v}</Text>,
                },
                {
                  title: '实例类型',
                  dataIndex: 'instance_type',
                  render: (v: string) => <Tag color="geekblue">{v}</Tag>,
                },
                { title: '目标', dataIndex: 'target', width: 70 },
                { title: '当前', dataIndex: 'count', width: 70 },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card
            title={
              <Space>
                <ApartmentOutlined />
                Instance Groups · Live ({instance_groups_live.length})
              </Space>
            }
            style={{ borderRadius: 12 }}
            extra={
              <Tag color={syncTagColor(sync_status)}>{syncLabel(sync_status)}</Tag>
            }
          >
            <Table
              rowKey={(r) => r.instance_group_name}
              size="small"
              pagination={false}
              dataSource={instance_groups_live}
              locale={{ emptyText: 'AWS 未返回数据' }}
              columns={[
                {
                  title: '名称',
                  dataIndex: 'instance_group_name',
                  render: (v: string) => <Text strong>{v}</Text>,
                },
                {
                  title: '实例类型',
                  dataIndex: 'instance_type',
                  render: (v: string) => <Tag color="geekblue">{v}</Tag>,
                },
                { title: '目标', dataIndex: 'target_count', width: 70 },
                { title: '当前', dataIndex: 'current_count', width: 70 },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 100,
                  render: (v?: string) =>
                    v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">—</Text>,
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* Health detail + Advanced features */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={10}>
          <Card
            title={
              <Space>
                <CloudServerOutlined />
                节点健康
              </Space>
            }
            style={{ borderRadius: 12 }}
          >
            <Row gutter={[16, 16]}>
              <Col span={12}>
                <Progress
                  type="circle"
                  percent={healthPct}
                  strokeColor={token.colorSuccess}
                  size={140}
                  format={() => (
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 22, fontWeight: 600 }}>
                        {health.ready}/{health.total}
                      </div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        Ready
                      </Text>
                    </div>
                  )}
                />
              </Col>
              <Col span={12}>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="Ready">
                    <Badge status="success" text={String(health.ready)} />
                  </Descriptions.Item>
                  <Descriptions.Item label="NotReady">
                    <Badge status="error" text={String(health.notready)} />
                  </Descriptions.Item>
                  <Descriptions.Item label="Unknown">
                    <Badge status="default" text={String(health.unknown)} />
                  </Descriptions.Item>
                  <Descriptions.Item label="Total">
                    <Text strong>{health.total}</Text>
                  </Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} xl={14}>
          <Card
            title={
              <Space>
                <ThunderboltOutlined />
                高级特性
              </Space>
            }
            style={{ borderRadius: 12, height: '100%' }}
          >
            {Object.keys(advanced_features).length === 0 ? (
              <Text type="secondary">暂无数据</Text>
            ) : (
              <Space size={[8, 8]} wrap>
                {Object.entries(advanced_features).map(([feature, value]) => {
                  const { color, label } = renderAdvancedFeature(feature, value);
                  return (
                    <Tag key={feature} color={color}>
                      {label}
                    </Tag>
                  );
                })}
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      {/* Quota table · AWS ComputeQuota × resources expanded */}
      <Card
        title={
          <Space>
            <ThunderboltOutlined />
            配额 · ComputeQuota ({quotaList?.quotas.length ?? 0} 条 ·{' '}
            {quotaRows.length} 资源行)
          </Space>
        }
        style={{ borderRadius: 12, marginTop: 16 }}
        extra={
          <Space size={24} wrap>
            {grandTotals && (
              <>
                <Statistic
                  title="总 GPU"
                  value={
                    grandTotals.hasAnyUsage
                      ? `${grandTotals.gpuUsed}/${grandTotals.gpuQuota} 卡`
                      : `${grandTotals.gpuQuota} 卡`
                  }
                  valueStyle={{ fontSize: 14, fontWeight: 600 }}
                />
                <Statistic
                  title="总利用率"
                  value={
                    grandTotals.hasAnyUsage
                      ? Math.round(grandTotals.pct)
                      : '—'
                  }
                  suffix={grandTotals.hasAnyUsage ? '%' : ''}
                  valueStyle={{
                    fontSize: 14,
                    fontWeight: 600,
                    color: grandTotals.hasAnyUsage
                      ? utilColor(grandTotals.pct, token)
                      : undefined,
                  }}
                />
              </>
            )}
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={openCreateModal}
              // Creation requires the workspace list so we can resolve
              // workspaceId → POST path. Quota list itself is not required.
              disabled={workspaces.length === 0}
            >
              新增配额
            </Button>
          </Space>
        }
      >
        {quotaError ? (
          <Alert
            type="error"
            showIcon
            message="配额 API 未就绪"
            description={quotaError}
            action={
              <Button size="small" onClick={() => void fetchQuotas()}>
                重试
              </Button>
            }
          />
        ) : (
          <Table<QuotaMatrixRow>
            rowKey="key"
            size="small"
            loading={quotaLoading}
            pagination={{ pageSize: 10, size: 'small', hideOnSinglePage: true }}
            dataSource={quotaRows}
            locale={{ emptyText: '暂无配额数据' }}
            columns={[
              {
                title: 'Team / Workspace',
                dataIndex: 'workspaceDisplayName',
                render: (_: unknown, row) => (
                  <Space direction="vertical" size={0}>
                    <Text strong>{row.workspaceDisplayName}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {row.teamName}
                    </Text>
                  </Space>
                ),
              },
              {
                title: 'Instance Type',
                render: (_: unknown, row) => {
                  const gpuType = row.resource.gpuType ?? null;
                  return (
                    <Space size={4} wrap>
                      <Tag color="geekblue">{row.resource.instanceType}</Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        × {row.resource.count}
                      </Text>
                      {gpuType && (
                        <Tag
                          color="purple"
                          style={{ fontSize: 11, marginInlineEnd: 0 }}
                        >
                          {gpuType}
                        </Tag>
                      )}
                    </Space>
                  );
                },
              },
              {
                title: 'GPU 配额/已用',
                width: 260,
                render: (_: unknown, row) => {
                  const quotaGpu =
                    row.resource.accelerators * row.resource.count;
                  const usage = usageMap[row.teamName] ?? null;
                  // Usage aggregates across all instance types for the team;
                  // we can't split it per-row without more server data, so we
                  // show team-level usage on the row whose instanceType matches.
                  const perTypeUsage = usage?.resources.find(
                    (u) => u.instanceType === row.resource.instanceType,
                  );
                  const gpuUsed = perTypeUsage?.acceleratorsUsed ?? null;
                  const pending = perTypeUsage?.acceleratorsPending ?? 0;
                  const hasUsage = gpuUsed !== null;
                  const pct =
                    hasUsage && quotaGpu > 0
                      ? Math.max(
                          0,
                          Math.min(
                            100,
                            Math.round(((gpuUsed as number) / quotaGpu) * 100),
                          ),
                        )
                      : 0;
                  return (
                    <Space direction="vertical" size={2} style={{ width: '100%' }}>
                      <Space size={6} align="baseline">
                        {hasUsage ? (
                          <Text style={{ fontSize: 12 }}>
                            {gpuUsed}/{quotaGpu} 卡 · {pct}%
                          </Text>
                        ) : (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {quotaGpu} 卡 · 用量采集中
                          </Text>
                        )}
                        {pending > 0 && (
                          <Text type="warning" style={{ fontSize: 11 }}>
                            +{pending} pending
                          </Text>
                        )}
                      </Space>
                      <Progress
                        percent={hasUsage ? pct : 0}
                        strokeColor={
                          hasUsage
                            ? utilColor(pct, token)
                            : token.colorBorderSecondary
                        }
                        size="small"
                        showInfo={false}
                      />
                    </Space>
                  );
                },
              },
              {
                title: 'CPU 配额 · 利用率',
                width: 220,
                render: (_: unknown, row) => {
                  const cores = row.resource.vCpu * row.resource.count;
                  const usage = usageMap[row.teamName] ?? null;
                  const perType = usage?.resources.find(
                    (u) => u.instanceType === row.resource.instanceType,
                  );
                  const usedCores = perType?.vCpuUsed ?? null;
                  const hasUsage = usedCores !== null;
                  const pct =
                    hasUsage && cores > 0
                      ? Math.max(
                          0,
                          Math.min(
                            100,
                            Math.round(((usedCores as number) / cores) * 100),
                          ),
                        )
                      : 0;
                  return (
                    <Space direction="vertical" size={2} style={{ width: '100%' }}>
                      <Text
                        style={{ fontSize: 12 }}
                        type={hasUsage ? undefined : 'secondary'}
                      >
                        {hasUsage
                          ? `${(usedCores as number).toFixed(1)}/${cores} 核 · ${pct}%`
                          : `${cores} 核 · 用量采集中`}
                      </Text>
                      <Progress
                        percent={hasUsage ? pct : 0}
                        strokeColor={
                          hasUsage
                            ? utilColor(pct, token)
                            : token.colorBorderSecondary
                        }
                        size="small"
                        showInfo={false}
                      />
                    </Space>
                  );
                },
              },
              {
                title: '内存配额 · 利用率',
                width: 220,
                render: (_: unknown, row) => {
                  const gib = row.resource.memoryInGiB * row.resource.count;
                  const usage = usageMap[row.teamName] ?? null;
                  const perType = usage?.resources.find(
                    (u) => u.instanceType === row.resource.instanceType,
                  );
                  const usedGib = perType?.memoryUsedInGiB ?? null;
                  const hasUsage = usedGib !== null;
                  const pct =
                    hasUsage && gib > 0
                      ? Math.max(
                          0,
                          Math.min(
                            100,
                            Math.round(((usedGib as number) / gib) * 100),
                          ),
                        )
                      : 0;
                  return (
                    <Space direction="vertical" size={2} style={{ width: '100%' }}>
                      <Text
                        style={{ fontSize: 12 }}
                        type={hasUsage ? undefined : 'secondary'}
                      >
                        {hasUsage
                          ? `${(usedGib as number).toFixed(1)}/${gib} GiB · ${pct}%`
                          : `${gib} GiB · 用量采集中`}
                      </Text>
                      <Progress
                        percent={hasUsage ? pct : 0}
                        strokeColor={
                          hasUsage
                            ? utilColor(pct, token)
                            : token.colorBorderSecondary
                        }
                        size="small"
                        showInfo={false}
                      />
                    </Space>
                  );
                },
              },
              {
                title: 'FairShare',
                width: 110,
                render: (_: unknown, row) => (
                  <Tag color="blue">权重 {row.parent.target.fairShareWeight}</Tag>
                ),
              },
              {
                title: '状态',
                width: 100,
                render: (_: unknown, row) => (
                  <Tag
                    color={
                      row.parent.activationState === 'Enabled'
                        ? 'green'
                        : 'default'
                    }
                  >
                    {row.parent.activationState === 'Enabled' ? '已启用' : '已禁用'}
                  </Tag>
                ),
              },
              {
                title: '操作',
                width: 160,
                fixed: 'right',
                render: (_: unknown, row) => (
                  <Space size={0}>
                    <Button
                      type="link"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => openEditDrawer(row)}
                    >
                      编辑
                    </Button>
                    <Popconfirm
                      title="删除整个 ComputeQuota?"
                      description={`${row.workspaceDisplayName} · ${row.parent.name}（含 ${row.parent.resources.length} 个资源行）`}
                      okText="删除"
                      okButtonProps={{ danger: true }}
                      cancelText="取消"
                      onConfirm={() => handleDelete(row)}
                    >
                      <Button
                        type="link"
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        loading={deletingKey === row.key}
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Drawer
        title={
          editTarget
            ? `编辑配额 · ${editTarget.workspaceDisplayName} · ${editTarget.resource.instanceType}`
            : '编辑配额'
        }
        width={480}
        open={editTarget !== null}
        onClose={closeEditDrawer}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={closeEditDrawer}>取消</Button>
            <Button type="primary" loading={editSaving} onClick={handleEditSave}>
              保存
            </Button>
          </Space>
        }
      >
        {editTarget && (
          <Form<QuotaEditFormValues> form={editForm} layout="vertical">
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={`ComputeQuotaId: ${editTarget.computeQuotaId}`}
              description={`版本 v${editTarget.parent.computeQuotaVersion ?? '?'} · 状态 ${editTarget.parent.status}`}
            />
            <Form.Item
              name="count"
              label="实例数"
              rules={[{ required: true, message: '必填' }]}
              extra={`当前 ${editTarget.resource.instanceType}`}
            >
              <InputNumber min={0} step={1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="accelerators"
              label="每实例 GPU/加速器数"
              rules={[{ required: true, message: '必填' }]}
              extra="总 GPU = 实例数 × 每实例 GPU 数"
            >
              <InputNumber min={0} step={1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="fairShareWeight"
              label="FairShareWeight (1-100)"
              rules={[{ required: true, message: '必填' }]}
              extra="替代原 low/normal/high · 越大越优先"
            >
              <InputNumber min={1} max={100} step={1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="sharingStrategy"
              label="资源借用策略"
              rules={[{ required: true, message: '必选' }]}
            >
              <Select
                options={[
                  { value: 'LendAndBorrow', label: 'LendAndBorrow · 双向借用' },
                  { value: 'Lend', label: 'Lend · 仅借出' },
                  { value: 'DontLend', label: 'DontLend · 不借出' },
                ]}
              />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, curr) =>
                prev.sharingStrategy !== curr.sharingStrategy
              }
            >
              {({ getFieldValue }) =>
                getFieldValue('sharingStrategy') === 'LendAndBorrow' && (
                  <Form.Item
                    name="borrowLimit"
                    label="借用上限 (%)"
                    extra="仅 LendAndBorrow 生效 · 留空表示无限制"
                  >
                    <InputNumber
                      min={0}
                      max={500}
                      step={10}
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                )
              }
            </Form.Item>
            <Form.Item
              name="preemptTeamTasks"
              label="抢占策略"
              rules={[{ required: true, message: '必选' }]}
            >
              <Select
                options={[
                  { value: 'LowerPriority', label: 'LowerPriority · 抢占低优先级' },
                  { value: 'Never', label: 'Never · 从不抢占' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="activationState"
              label="激活状态"
              rules={[{ required: true, message: '必选' }]}
            >
              <Select
                options={[
                  { value: 'Enabled', label: 'Enabled · 已启用' },
                  { value: 'Disabled', label: 'Disabled · 已禁用' },
                ]}
              />
            </Form.Item>
            <Form.Item name="description" label="描述">
              <Input.TextArea rows={2} placeholder="可选描述" />
            </Form.Item>
            {(() => {
              const usage = usageMap[editTarget.teamName] ?? null;
              const perType = usage?.resources.find(
                (u) => u.instanceType === editTarget.resource.instanceType,
              );
              if (!perType) {
                return (
                  <Alert
                    type="warning"
                    showIcon
                    message="当前使用情况"
                    description="用量采集中,保存配额不影响运行中任务。"
                  />
                );
              }
              const totalGpu =
                editTarget.resource.accelerators * editTarget.resource.count;
              return (
                <Alert
                  type="info"
                  showIcon
                  message="当前使用情况"
                  description={
                    <Space direction="vertical" size={2}>
                      <Text style={{ fontSize: 12 }}>
                        GPU 已用 {perType.acceleratorsUsed}/{totalGpu} · pending{' '}
                        {perType.acceleratorsPending}
                      </Text>
                      <Text style={{ fontSize: 12 }}>
                        CPU 已用 {perType.vCpuUsed.toFixed(1)} 核
                      </Text>
                      <Text style={{ fontSize: 12 }}>
                        内存已用 {perType.memoryUsedInGiB.toFixed(1)} GiB
                      </Text>
                    </Space>
                  }
                />
              );
            })()}
          </Form>
        )}
      </Drawer>

      {/* Create-quota modal · POST /workspaces/{wsId}/quota creates a fresh
          ComputeQuota with one resource row and binds it to the workspace. */}
      <Modal
        title="新增配额"
        open={createOpen}
        onCancel={closeCreateModal}
        onOk={handleCreateSave}
        okText="创建"
        cancelText="取消"
        confirmLoading={createSaving}
        destroyOnClose
        width={520}
      >
        <Form<QuotaCreateFormValues> form={createForm} layout="vertical">
          <Form.Item
            name="workspaceId"
            label="工作空间"
            rules={[{ required: true, message: '必选' }]}
            extra="配额绑到该 workspace · AWS target.teamName 自动用 workspace.name"
          >
            <Select
              placeholder="选择工作空间"
              showSearch
              optionFilterProp="label"
              options={workspaces.map((ws) => ({
                value: ws.id,
                label: `${ws.display_name} · ${ws.name}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
          <Form.Item
            name="instanceType"
            label="Instance Type"
            rules={[{ required: true, message: '必选' }]}
          >
            <Select
              placeholder="选择实例类型"
              showSearch
              loading={instanceTypesLoading}
              options={clusterInstanceTypes.map((t) => ({
                value: t.instance_type,
                label: t.gpu_type ? `${t.instance_type} · ${t.gpu_type}` : t.instance_type,
              }))}
            />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="count"
                label="实例数"
                rules={[{ required: true, message: '必填' }]}
              >
                <InputNumber min={0} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="accelerators"
                label="每实例 GPU 数"
                rules={[{ required: true, message: '必填' }]}
                extra="总 GPU = 实例数 × 该值"
              >
                <InputNumber min={0} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="fairShareWeight"
            label="FairShareWeight (1-100)"
            rules={[{ required: true, message: '必填' }]}
            extra="预设: 30 低 / 50 默认 / 80 高"
          >
            <InputNumber min={1} max={100} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="sharingStrategy"
            label="资源借用策略"
            rules={[{ required: true, message: '必选' }]}
          >
            <Select
              options={[
                { value: 'LendAndBorrow', label: 'LendAndBorrow · 双向借用' },
                { value: 'Lend', label: 'Lend · 仅借出' },
                { value: 'DontLend', label: 'DontLend · 不借出' },
              ]}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, curr) =>
              prev.sharingStrategy !== curr.sharingStrategy
            }
          >
            {({ getFieldValue }) =>
              getFieldValue('sharingStrategy') === 'LendAndBorrow' && (
                <Form.Item
                  name="borrowLimit"
                  label="借用上限 (%)"
                  rules={[
                    { required: true, message: 'LendAndBorrow 必须填 BorrowLimit' },
                  ]}
                  extra="AWS 要求 0-500 · 100 表示最多借用 1× 基线"
                >
                  <InputNumber
                    min={0}
                    max={500}
                    step={10}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              )
            }
          </Form.Item>
          <Form.Item
            name="preemptTeamTasks"
            label="抢占策略"
            rules={[{ required: true, message: '必选' }]}
          >
            <Select
              options={[
                { value: 'LowerPriority', label: 'LowerPriority · 抢占低优先级' },
                { value: 'Never', label: 'Never · 从不抢占' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="activationState"
            label="激活状态"
            rules={[{ required: true, message: '必选' }]}
          >
            <Select
              options={[
                { value: 'Enabled', label: 'Enabled · 已启用' },
                { value: 'Disabled', label: 'Disabled · 已禁用' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}

/** Color scale for utilization % : <70% green · 70–90% orange · >90% red. */
function utilColor(pct: number, token: ReturnType<typeof theme.useToken>['token']): string {
  if (pct >= 90) return token.colorError;
  if (pct >= 70) return token.colorWarning;
  return token.colorSuccess;
}

