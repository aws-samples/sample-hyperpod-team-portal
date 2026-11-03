/**
 * /admin/storage — combined "Storage & Permissions" page (M1 mock-first).
 *
 * Three tabs persisted via the `tab` query string (?tab=file-systems | permission-groups | datasets):
 *   · Tab 1 "文件系统"     · FSx Lustre physical instances + capacity.
 *   · Tab 2 "权限组"       · Sub-path containers + POSIX uid/gid + PathGrants.
 *   · Tab 3 "数据集(快捷)" · Read-only view over PathGrants where dataset_name is set.
 *
 * Admin-only affordances (`新建文件系统` / `删除文件系统`) are gated by IS_ADMIN.
 * Non-admin users only see permission groups scoped to their current workspace
 * plus global (workspace_id=NULL) groups.
 *
 * All data is mock (see src/mock/storage.ts). Writes update local state and
 * show a toast noting the M2 backend hook-up point.
 */
import { useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Tree,
  Typography,
  message,
  theme,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { DataNode } from 'antd/es/tree';
import { PageContainer } from '@ant-design/pro-components';
import {
  ApartmentOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  HddOutlined,
  LinkOutlined,
  PlusOutlined,
  SafetyOutlined,
} from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import relativeTime from 'dayjs/plugin/relativeTime';
import { useAppStore } from '@/store';
import { mockUsers } from '@/mock/users';
import {
  MOCK_FILE_SYSTEMS,
  MOCK_PATH_GRANTS,
  MOCK_PERMISSION_GROUPS,
  type FsxDeploymentType,
  type GrantMode,
  type MockFsxFileSystem,
  type MockPathGrant,
  type MockPermissionGroup,
  type WorkspaceRole,
} from '@/mock/storage';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const { Text, Paragraph, Link: AntLink } = Typography;

/** Demo gate — M2 replaces with `useAppStore(s => s.currentUser.role === 'admin')`. */
const IS_ADMIN = true;

/** Valid tab keys, used for query-string persistence. */
type TabKey = 'file-systems' | 'permission-groups' | 'datasets';
const VALID_TABS: readonly TabKey[] = ['file-systems', 'permission-groups', 'datasets'];
const isTabKey = (v: string | null): v is TabKey =>
  v !== null && (VALID_TABS as readonly string[]).includes(v);

/** Role options shown in the "授权对象" role picker. */
const ROLE_OPTIONS: { value: WorkspaceRole; label: string }[] = [
  { value: 'owner', label: '负责人 (owner)' },
  { value: 'admin', label: '管理员 (admin)' },
  { value: 'developer', label: '开发者 (developer)' },
  { value: 'viewer', label: '只读 (viewer)' },
];

/** Color for the deployment-type tag. */
const deploymentColor = (dt: FsxDeploymentType): string =>
  dt === 'PERSISTENT_2' ? 'geekblue' : 'cyan';

/** GB → TB with one decimal; keeps small values in GB. */
const prettyCapacity = (gb: number): string =>
  gb >= 1000 ? `${(gb / 1000).toFixed(1)} TB` : `${gb} GB`;

/** Format large counts for datasets (e.g. 1.28M). */
const prettyCount = (n: number): string => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
};

/* ============================================================================
 * Main page
 * ========================================================================== */

export default function AdminStorage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const activeTab: TabKey = isTabKey(tabParam) ? tabParam : 'file-systems';

  // Single source of truth for all three tabs.
  const [fileSystems, setFileSystems] = useState<MockFsxFileSystem[]>(MOCK_FILE_SYSTEMS);
  const [permissionGroups, setPermissionGroups] =
    useState<MockPermissionGroup[]>(MOCK_PERMISSION_GROUPS);
  const [pathGrants, setPathGrants] = useState<MockPathGrant[]>(MOCK_PATH_GRANTS);

  /**
   * Cross-tab navigation requests:
   *   - `selectPgId`  — when Tab 3 "去权限组查看" is clicked we jump to Tab 2 and
   *     auto-select the matching permission group.
   *   - `selectGrantId` — then highlights the row for that grant.
   *   - `filterFsId`  — Tab 1 → Tab 2 "查看权限组" filters the tree to one fs.
   */
  const [crossTab, setCrossTab] = useState<{
    selectPgId?: string;
    selectGrantId?: string;
    filterFsId?: string;
  }>({});

  const switchTab = (next: TabKey, extra?: typeof crossTab) => {
    const params = new URLSearchParams(searchParams);
    params.set('tab', next);
    setSearchParams(params, { replace: true });
    if (extra) setCrossTab(extra);
  };

  // Aggregate stats for the tab-bar header row (cheap, memoized).
  const stats = useMemo(() => {
    const totalCapacity = fileSystems.reduce((a, f) => a + f.storage_capacity_gb, 0);
    const totalUsed = fileSystems.reduce((a, f) => a + f.used_gb, 0);
    return {
      fsCount: fileSystems.length,
      totalCapacity,
      totalUsed,
      pgCount: permissionGroups.length,
    };
  }, [fileSystems, permissionGroups]);

  return (
    <PageContainer
      title="存储与权限"
      subTitle="FSx Lustre 文件系统 · 路径级 POSIX 授权 · 数据集别名"
    >
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="文件系统" value={stats.fsCount} suffix="个" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="总容量" value={prettyCapacity(stats.totalCapacity)} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已用容量"
              value={prettyCapacity(stats.totalUsed)}
              suffix={`/ ${Math.round((stats.totalUsed / stats.totalCapacity) * 100)}%`}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="权限组" value={stats.pgCount} suffix="组" />
          </Card>
        </Col>
      </Row>

      <Tabs
        activeKey={activeTab}
        onChange={(k) => switchTab(k as TabKey)}
        destroyInactiveTabPane={false}
        items={[
          {
            key: 'file-systems',
            label: (
              <span>
                <HddOutlined /> 文件系统
              </span>
            ),
            children: (
              <FileSystemsTab
                fileSystems={fileSystems}
                permissionGroups={permissionGroups}
                onCreate={(fs) => setFileSystems((prev) => [...prev, fs])}
                onDelete={(id) =>
                  setFileSystems((prev) => prev.filter((f) => f.id !== id))
                }
                onViewPermissionGroups={(fsId) =>
                  switchTab('permission-groups', { filterFsId: fsId })
                }
                onCreatePermissionGroup={(fsId) =>
                  switchTab('permission-groups', { filterFsId: fsId })
                }
              />
            ),
          },
          {
            key: 'permission-groups',
            label: (
              <span>
                <SafetyOutlined /> 权限组
              </span>
            ),
            children: (
              <PermissionGroupsTab
                fileSystems={fileSystems}
                permissionGroups={permissionGroups}
                pathGrants={pathGrants}
                preselectPgId={crossTab.selectPgId}
                preselectGrantId={crossTab.selectGrantId}
                filterFsId={crossTab.filterFsId}
                onClearCross={() => setCrossTab({})}
                onCreateGroup={(g) =>
                  setPermissionGroups((prev) => [...prev, g])
                }
                onCreateGrant={(g) => setPathGrants((prev) => [...prev, g])}
                onDeleteGrant={(id) =>
                  setPathGrants((prev) => prev.filter((g) => g.id !== id))
                }
              />
            ),
          },
          {
            key: 'datasets',
            label: (
              <span>
                <DatabaseOutlined /> 数据集(快捷)
              </span>
            ),
            children: (
              <DatasetsTab
                permissionGroups={permissionGroups}
                pathGrants={pathGrants}
                onOpenInPermissionGroups={(pgId, grantId) =>
                  switchTab('permission-groups', {
                    selectPgId: pgId,
                    selectGrantId: grantId,
                  })
                }
              />
            ),
          },
        ]}
      />
    </PageContainer>
  );
}

/* ============================================================================
 * Tab 1 · 文件系统
 * ========================================================================== */

interface FileSystemsTabProps {
  fileSystems: MockFsxFileSystem[];
  permissionGroups: MockPermissionGroup[];
  onCreate: (fs: MockFsxFileSystem) => void;
  onDelete: (id: string) => void;
  onViewPermissionGroups: (fsId: string) => void;
  onCreatePermissionGroup: (fsId: string) => void;
}

function FileSystemsTab({
  fileSystems,
  permissionGroups,
  onCreate,
  onDelete,
  onViewPermissionGroups,
  onCreatePermissionGroup,
}: FileSystemsTabProps) {
  const { token } = theme.useToken();
  const [createOpen, setCreateOpen] = useState(false);

  const pgCountByFs = useMemo(() => {
    const m = new Map<string, number>();
    for (const pg of permissionGroups) {
      m.set(pg.file_system_id, (m.get(pg.file_system_id) ?? 0) + 1);
    }
    return m;
  }, [permissionGroups]);

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="📌 M1 mock · M2 接 AWS FSx CreateFileSystem · 当前无真实文件系统"
        description="新建按钮会在本地添加一条 mock,不会真正调用 AWS 控制台。"
      />

      <Space style={{ marginBottom: 16, justifyContent: 'flex-end', display: 'flex' }}>
        {IS_ADMIN && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新建文件系统
          </Button>
        )}
      </Space>

      <Row gutter={[16, 16]}>
        {fileSystems.map((fs) => {
          const pct = Math.round((fs.used_gb / fs.storage_capacity_gb) * 100);
          const pgCount = pgCountByFs.get(fs.id) ?? 0;
          const progressStatus =
            pct >= 90 ? 'exception' : pct >= 75 ? 'active' : 'normal';
          return (
            <Col xs={24} lg={12} key={fs.id}>
              <Card
                title={
                  <Space>
                    <CloudServerOutlined style={{ color: token.colorPrimary }} />
                    <span style={{ fontWeight: 600 }}>{fs.display_name}</span>
                    <Badge
                      status={fs.state === 'Available' ? 'success' : 'processing'}
                      text={fs.state}
                    />
                    <Tag color={deploymentColor(fs.deployment_type)}>
                      {fs.deployment_type}
                    </Tag>
                  </Space>
                }
                extra={
                  <Space>
                    <Button
                      size="small"
                      icon={<SafetyOutlined />}
                      onClick={() => onViewPermissionGroups(fs.id)}
                    >
                      查看权限组({pgCount})
                    </Button>
                    <Button
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={() => onCreatePermissionGroup(fs.id)}
                    >
                      新建权限组
                    </Button>
                    {IS_ADMIN && (
                      <Popconfirm
                        title="删除文件系统"
                        description="该操作不可逆且会级联影响其下权限组,请确认。"
                        okText="删除"
                        okButtonProps={{ danger: true }}
                        cancelText="取消"
                        onConfirm={() => {
                          onDelete(fs.id);
                          message.success(`已删除 ${fs.display_name}(M1 mock)`);
                        }}
                      >
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    )}
                  </Space>
                }
              >
                <Descriptions size="small" column={2} colon>
                  <Descriptions.Item label="FSx ID">
                    <Text code>{fs.fsx_id}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="Lustre">{fs.lustre_version}</Descriptions.Item>
                  <Descriptions.Item label="挂载 DNS" span={2}>
                    <Text code style={{ fontSize: 12 }}>
                      {fs.mount_dns}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="Mount Name">
                    <Text code>{fs.mount_name}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="吞吐">
                    {fs.throughput_mbps_per_tb} MB/s per TiB
                  </Descriptions.Item>
                  <Descriptions.Item label="VPC">
                    <Text code style={{ fontSize: 12 }}>
                      {fs.vpc_id}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="Subnet">
                    <Text code style={{ fontSize: 12 }}>
                      {fs.subnet_id}
                    </Text>
                  </Descriptions.Item>
                </Descriptions>

                <div style={{ marginTop: 12 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      容量 {prettyCapacity(fs.used_gb)} / {prettyCapacity(fs.storage_capacity_gb)}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      创建于 {dayjs(fs.created_at).format('YYYY-MM-DD')}
                    </Text>
                  </Space>
                  <Progress percent={pct} status={progressStatus} />
                </div>
              </Card>
            </Col>
          );
        })}
      </Row>

      <CreateFileSystemModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={(fs) => {
          onCreate(fs);
          setCreateOpen(false);
          message.success(
            `已添加 ${fs.display_name}(M1 mock,M2 真调 CreateFileSystem)`,
          );
        }}
      />
    </>
  );
}

interface CreateFileSystemModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (fs: MockFsxFileSystem) => void;
}

function CreateFileSystemModal({ open, onClose, onCreate }: CreateFileSystemModalProps) {
  const [form] = Form.useForm<{
    display_name: string;
    storage_capacity_gb: number;
    deployment_type: FsxDeploymentType;
  }>();

  const handleOk = async () => {
    const values = await form.validateFields();
    const rand = Math.random().toString(36).slice(2, 10);
    const newFs: MockFsxFileSystem = {
      id: `fs-uuid-${rand}`,
      fsx_id: `fs-${rand}`,
      display_name: values.display_name,
      lustre_version: '2.15',
      storage_capacity_gb: values.storage_capacity_gb,
      used_gb: 0,
      deployment_type: values.deployment_type,
      state: 'Creating',
      throughput_mbps_per_tb: values.deployment_type === 'PERSISTENT_2' ? 125 : 250,
      mount_dns: `fs-${rand}.fsx.us-west-2.amazonaws.com`,
      mount_name: rand.slice(0, 8),
      vpc_id: 'vpc-0a1b2c3d',
      subnet_id: 'subnet-0a1b2c3d',
      created_at: new Date().toISOString(),
    };
    onCreate(newFs);
    form.resetFields();
  };

  return (
    <Modal
      title="新建文件系统"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="创建"
      cancelText="取消"
      destroyOnClose
    >
      <Alert
        type="warning"
        showIcon
        message="M1 mock · 不会真调 AWS"
        style={{ marginBottom: 16 }}
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          storage_capacity_gb: 1200,
          deployment_type: 'SCRATCH_2' as FsxDeploymentType,
        }}
        preserve={false}
      >
        <Form.Item
          label="显示名称"
          name="display_name"
          rules={[{ required: true, message: '请输入名称' }]}
        >
          <Input placeholder="e.g. team-c-datasets" maxLength={64} />
        </Form.Item>
        <Form.Item
          label="容量 (GB)"
          name="storage_capacity_gb"
          rules={[{ required: true }]}
          extra="FSx Lustre SSD 最小 1200 GB(1.2 TB)"
        >
          <InputNumber min={1200} step={1200} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item
          label="部署类型"
          name="deployment_type"
          rules={[{ required: true }]}
        >
          <Radio.Group>
            <Radio.Button value="SCRATCH_2">SCRATCH_2 · 高吞吐 250 MB/s</Radio.Button>
            <Radio.Button value="PERSISTENT_2">PERSISTENT_2 · 长期存储</Radio.Button>
          </Radio.Group>
        </Form.Item>
      </Form>
    </Modal>
  );
}

/* ============================================================================
 * Tab 2 · 权限组
 * ========================================================================== */

interface PermissionGroupsTabProps {
  fileSystems: MockFsxFileSystem[];
  permissionGroups: MockPermissionGroup[];
  pathGrants: MockPathGrant[];
  preselectPgId?: string;
  preselectGrantId?: string;
  filterFsId?: string;
  onClearCross: () => void;
  onCreateGroup: (g: MockPermissionGroup) => void;
  onCreateGrant: (g: MockPathGrant) => void;
  onDeleteGrant: (id: string) => void;
}

function PermissionGroupsTab({
  fileSystems,
  permissionGroups,
  pathGrants,
  preselectPgId,
  preselectGrantId,
  filterFsId,
  onClearCross,
  onCreateGroup,
  onCreateGrant,
  onDeleteGrant,
}: PermissionGroupsTabProps) {
  const currentUser = useAppStore((s) => s.currentUser);
  const currentWsId = useAppStore((s) => s.currentWorkspaceId);

  // Non-admin: filter to own workspace + global groups only.
  const visibleGroups = useMemo(() => {
    const base = IS_ADMIN
      ? permissionGroups
      : permissionGroups.filter(
          (g) => g.workspace_id === currentWsId || g.workspace_id === null,
        );
    return filterFsId ? base.filter((g) => g.file_system_id === filterFsId) : base;
  }, [permissionGroups, currentWsId, filterFsId]);

  const [selectedPgId, setSelectedPgId] = useState<string | undefined>(
    preselectPgId ?? visibleGroups[0]?.id,
  );
  const [createGroupOpen, setCreateGroupOpen] = useState(false);
  const [createGrantOpen, setCreateGrantOpen] = useState(false);

  // Apply incoming cross-tab preselects (once) whenever they change.
  useMemo(() => {
    if (preselectPgId) setSelectedPgId(preselectPgId);
  }, [preselectPgId]);

  const selectedPg = useMemo(
    () => visibleGroups.find((g) => g.id === selectedPgId),
    [visibleGroups, selectedPgId],
  );

  const selectedGrants = useMemo(
    () => (selectedPg ? pathGrants.filter((g) => g.permission_group_id === selectedPg.id) : []),
    [pathGrants, selectedPg],
  );

  // Build tree: group by workspace (global separate).
  const treeData: DataNode[] = useMemo(() => {
    const byWs = new Map<string, MockPermissionGroup[]>();
    for (const pg of visibleGroups) {
      const key = pg.workspace_id ?? '__global__';
      const list = byWs.get(key) ?? [];
      list.push(pg);
      byWs.set(key, list);
    }

    return Array.from(byWs.entries()).map(([wsKey, groups]) => {
      const wsLabel =
        wsKey === '__global__'
          ? '🌐 global(全局共享)'
          : `👥 ${groups[0]!.workspace_display_name ?? groups[0]!.workspace_name}`;
      return {
        key: `ws-${wsKey}`,
        title: <Text strong>{wsLabel}</Text>,
        selectable: false,
        children: groups.map((pg) => {
          const pct = Math.round((pg.used_gb / pg.quota_gb) * 100);
          return {
            key: pg.id,
            title: (
              <div style={{ paddingBlock: 4 }}>
                <Space size={6}>
                  <FolderOpenOutlined />
                  <Text>{pg.name}</Text>
                </Space>
                <div style={{ marginTop: 4 }}>
                  <Progress
                    percent={pct}
                    size="small"
                    status={pct >= 90 ? 'exception' : 'normal'}
                    format={() => (
                      <span style={{ fontSize: 11 }}>
                        {pg.used_gb}/{pg.quota_gb} GB
                      </span>
                    )}
                  />
                </div>
              </div>
            ),
          } satisfies DataNode;
        }),
      } satisfies DataNode;
    });
  }, [visibleGroups]);

  const expandedKeys = useMemo(
    () => treeData.map((n) => n.key as string),
    [treeData],
  );

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="📌 权限变更仅展示 · M2 真 initContainer chown + OPA 阻止越权挂载"
        description={
          filterFsId
            ? `已过滤到文件系统 ${fileSystems.find((f) => f.id === filterFsId)?.display_name ?? filterFsId} · `
            : undefined
        }
        action={
          filterFsId && (
            <Button size="small" onClick={onClearCross}>
              清除过滤
            </Button>
          )
        }
      />

      <Row gutter={16}>
        {/* Left: tree */}
        <Col xs={24} lg={6}>
          <Card
            size="small"
            title={
              <Space>
                <ApartmentOutlined />
                <span>权限组</span>
              </Space>
            }
            extra={
              <Tooltip title={IS_ADMIN ? '' : '仅管理员可新建'}>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  disabled={!IS_ADMIN}
                  onClick={() => setCreateGroupOpen(true)}
                >
                  新建
                </Button>
              </Tooltip>
            }
          >
            {visibleGroups.length === 0 ? (
              <Empty description="暂无权限组" />
            ) : (
              <Tree
                treeData={treeData}
                expandedKeys={expandedKeys}
                selectedKeys={selectedPgId ? [selectedPgId] : []}
                onSelect={(keys) => {
                  const k = keys[0];
                  if (typeof k === 'string' && !k.startsWith('ws-')) {
                    setSelectedPgId(k);
                  }
                }}
                blockNode
              />
            )}
          </Card>
        </Col>

        {/* Right: selected group detail */}
        <Col xs={24} lg={18}>
          {selectedPg ? (
            <PermissionGroupDetail
              pg={selectedPg}
              grants={selectedGrants}
              highlightGrantId={preselectGrantId}
              onAddGrant={() => setCreateGrantOpen(true)}
              onDeleteGrant={(id) => {
                onDeleteGrant(id);
                message.success('已移除授权(M1 mock)');
              }}
            />
          ) : (
            <Card>
              <Empty description="请在左侧选择权限组" />
            </Card>
          )}
        </Col>
      </Row>

      <CreatePermissionGroupModal
        open={createGroupOpen}
        fileSystems={fileSystems}
        defaultFsId={filterFsId}
        onClose={() => setCreateGroupOpen(false)}
        onCreate={(g) => {
          onCreateGroup(g);
          setSelectedPgId(g.id);
          setCreateGroupOpen(false);
          message.success(
            `已创建权限组 ${g.name}(M1 mock · M2 会触发 chown Job)`,
          );
        }}
      />

      {selectedPg && (
        <CreatePathGrantModal
          open={createGrantOpen}
          pg={selectedPg}
          grantedByUser={{
            id: currentUser?.id ?? '',
            displayName: currentUser?.display_name ?? '',
          }}
          onClose={() => setCreateGrantOpen(false)}
          onCreate={(g) => {
            onCreateGrant(g);
            setCreateGrantOpen(false);
            message.success(
              g.dataset_name
                ? `授权已创建 · 已登记数据集 ${g.dataset_name}`
                : '授权已创建',
            );
          }}
        />
      )}
    </>
  );
}

interface PermissionGroupDetailProps {
  pg: MockPermissionGroup;
  grants: MockPathGrant[];
  highlightGrantId?: string;
  onAddGrant: () => void;
  onDeleteGrant: (id: string) => void;
}

function PermissionGroupDetail({
  pg,
  grants,
  highlightGrantId,
  onAddGrant,
  onDeleteGrant,
}: PermissionGroupDetailProps) {
  const pct = Math.round((pg.used_gb / pg.quota_gb) * 100);

  const columns: ColumnsType<MockPathGrant> = [
    {
      title: '路径',
      dataIndex: 'path',
      key: 'path',
      width: 260,
      render: (p: string) => <Text code>{p}</Text>,
    },
    {
      title: '模式',
      dataIndex: 'mode',
      key: 'mode',
      width: 90,
      render: (m: GrantMode) => (
        <Tag color={m === 'rw' ? 'orange' : 'green'}>{m.toUpperCase()}</Tag>
      ),
    },
    {
      title: '授权对象',
      key: 'target',
      width: 160,
      render: (_v, g) =>
        g.user_id ? (
          <Tag color="purple">👤 {g.user_display_name}</Tag>
        ) : (
          <Tag color="blue">🎭 {g.workspace_role}</Tag>
        ),
    },
    {
      title: '数据集别名',
      dataIndex: 'dataset_name',
      key: 'dataset_name',
      width: 160,
      render: (n: string | null) =>
        n ? <Tag color="gold">{n}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '授权人',
      dataIndex: 'granted_by_display_name',
      key: 'granted_by',
      width: 110,
    },
    {
      title: '授权时间',
      dataIndex: 'granted_at',
      key: 'granted_at',
      width: 160,
      render: (t: string) => (
        <Tooltip title={dayjs(t).format('YYYY-MM-DD HH:mm:ss')}>
          {dayjs(t).fromNow()}
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'ops',
      width: 120,
      fixed: 'right',
      render: (_v, g) => (
        <Space size={4}>
          <Tooltip title="M2 支持编辑">
            <Button size="small" type="text" icon={<EditOutlined />} disabled />
          </Tooltip>
          <Popconfirm
            title="移除此授权?"
            okText="移除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => onDeleteGrant(g.id)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          <FolderOpenOutlined />
          <span style={{ fontWeight: 600 }}>{pg.name}</span>
          {pg.workspace_id === null && <Tag color="gold">全局</Tag>}
        </Space>
      }
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={onAddGrant}>
          新增授权
        </Button>
      }
    >
      <Descriptions column={3} size="small" colon bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="所属文件系统">
          {pg.file_system_display_name}
        </Descriptions.Item>
        <Descriptions.Item label="所属 Workspace">
          {pg.workspace_display_name ?? (
            <Tag color="gold">global</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="状态">
          <Badge status="success" text={pg.state} />
        </Descriptions.Item>
        <Descriptions.Item label="Subpath Root" span={3}>
          <Text code>{pg.subpath_root}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="POSIX uid">{pg.posix_uid}</Descriptions.Item>
        <Descriptions.Item label="POSIX gid">{pg.posix_gid}</Descriptions.Item>
        <Descriptions.Item label="说明">
          {pg.description ?? <Text type="secondary">—</Text>}
        </Descriptions.Item>
      </Descriptions>

      <div style={{ marginBottom: 16 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text>
            配额用量 <Text strong>{pg.used_gb} GB</Text> / {pg.quota_gb} GB
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            M3 真执行 Lustre Project Quota
          </Text>
        </Space>
        <Progress percent={pct} status={pct >= 90 ? 'exception' : 'normal'} />
      </div>

      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={grants}
        pagination={false}
        scroll={{ x: 'max-content' }}
        rowClassName={(g) => (g.id === highlightGrantId ? 'ant-table-row-selected' : '')}
        locale={{ emptyText: '暂无授权 · 点击"新增授权"创建' }}
      />
    </Card>
  );
}

interface CreatePermissionGroupModalProps {
  open: boolean;
  fileSystems: MockFsxFileSystem[];
  defaultFsId?: string;
  onClose: () => void;
  onCreate: (g: MockPermissionGroup) => void;
}

function CreatePermissionGroupModal({
  open,
  fileSystems,
  defaultFsId,
  onClose,
  onCreate,
}: CreatePermissionGroupModalProps) {
  const [form] = Form.useForm<{
    file_system_id: string;
    name: string;
    subpath_root: string;
    quota_gb: number;
    description?: string;
  }>();

  const handleOk = async () => {
    const values = await form.validateFields();
    const fs = fileSystems.find((f) => f.id === values.file_system_id);
    const rand = Math.random().toString(36).slice(2, 8);
    const newPg: MockPermissionGroup = {
      id: `pg-new-${rand}`,
      file_system_id: values.file_system_id,
      file_system_display_name: fs?.display_name ?? '',
      workspace_id: null,
      workspace_name: null,
      workspace_display_name: null,
      name: values.name,
      description: values.description,
      subpath_root: values.subpath_root,
      posix_uid: 10000 + Math.floor(Math.random() * 1000),
      posix_gid: 20000 + Math.floor(Math.random() * 1000),
      quota_gb: values.quota_gb,
      used_gb: 0,
      state: 'Available',
    };
    onCreate(newPg);
    form.resetFields();
  };

  return (
    <Modal
      title="新建权限组"
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="创建"
      cancelText="取消"
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          file_system_id: defaultFsId ?? fileSystems[0]?.id,
          quota_gb: 500,
        }}
        preserve={false}
      >
        <Form.Item
          label="文件系统"
          name="file_system_id"
          rules={[{ required: true }]}
        >
          <Select
            options={fileSystems.map((f) => ({
              value: f.id,
              label: `${f.display_name} (${f.fsx_id})`,
            }))}
          />
        </Form.Item>
        <Form.Item
          label="权限组名"
          name="name"
          rules={[{ required: true, message: '请输入名称' }]}
        >
          <Input placeholder="e.g. team-c-datasets" maxLength={64} />
        </Form.Item>
        <Form.Item
          label="Subpath Root"
          name="subpath_root"
          rules={[
            { required: true },
            { pattern: /^\/[a-zA-Z0-9\-_/]+$/, message: '必须以 / 开头,仅字母数字 - _ /' },
          ]}
          extra="FSx 内的绝对子路径,权限组下的授权都会拼在这后面。"
        >
          <Input placeholder="/team-c/datasets" />
        </Form.Item>
        <Form.Item
          label="容量配额 (GB)"
          name="quota_gb"
          rules={[{ required: true }]}
        >
          <InputNumber min={10} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item label="说明" name="description">
          <Input.TextArea rows={2} placeholder="该权限组的用途说明(可选)" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

interface CreatePathGrantModalProps {
  open: boolean;
  pg: MockPermissionGroup;
  grantedByUser: { id: string; displayName: string };
  onClose: () => void;
  onCreate: (g: MockPathGrant) => void;
}

function CreatePathGrantModal({
  open,
  pg,
  grantedByUser,
  onClose,
  onCreate,
}: CreatePathGrantModalProps) {
  type TargetKind = 'user' | 'role';
  interface Values {
    relative_path: string;
    mode: GrantMode;
    target_kind: TargetKind;
    user_id?: string;
    workspace_role?: WorkspaceRole;
    register_as_dataset: boolean;
    dataset_name?: string;
    dataset_description?: string;
    readme_url?: string;
  }
  const [form] = Form.useForm<Values>();
  const registerAsDataset = Form.useWatch('register_as_dataset', form);
  const targetKind = Form.useWatch('target_kind', form);

  const handleOk = async () => {
    const values = await form.validateFields();
    const fullPath = `${pg.subpath_root}/${values.relative_path.replace(/^\//, '')}`;
    const rand = Math.random().toString(36).slice(2, 8);
    const user =
      values.target_kind === 'user' && values.user_id
        ? mockUsers.find((u) => u.id === values.user_id)
        : null;
    const newGrant: MockPathGrant = {
      id: `g-new-${rand}`,
      permission_group_id: pg.id,
      path: fullPath,
      mode: values.mode,
      user_id: values.target_kind === 'user' ? (values.user_id ?? null) : null,
      user_display_name:
        values.target_kind === 'user' ? (user?.displayName ?? null) : null,
      workspace_role:
        values.target_kind === 'role' ? (values.workspace_role ?? null) : null,
      dataset_name: values.register_as_dataset ? (values.dataset_name ?? null) : null,
      dataset_description: values.register_as_dataset
        ? (values.dataset_description ?? null)
        : null,
      readme_url: values.register_as_dataset ? (values.readme_url ?? null) : null,
      granted_by_id: grantedByUser.id,
      granted_by_display_name: grantedByUser.displayName,
      granted_at: new Date().toISOString(),
      size_gb: 0,
      file_count: 0,
    };
    onCreate(newGrant);
    form.resetFields();
  };

  return (
    <Modal
      title={`新增授权 · 权限组 ${pg.name}`}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="创建"
      cancelText="取消"
      destroyOnClose
      width={600}
    >
      <Form<Values>
        form={form}
        layout="vertical"
        initialValues={{
          mode: 'ro' as GrantMode,
          target_kind: 'role' as TargetKind,
          workspace_role: 'developer' as WorkspaceRole,
          register_as_dataset: false,
        }}
        preserve={false}
      >
        <Form.Item
          label={
            <Space>
              相对路径
              <Text type="secondary" style={{ fontSize: 12 }}>
                会自动拼接到 <Text code>{pg.subpath_root}</Text> 后
              </Text>
            </Space>
          }
          name="relative_path"
          rules={[
            { required: true, message: '请输入相对路径' },
            { pattern: /^[a-zA-Z0-9\-_/]+$/, message: '仅字母数字 - _ /' },
          ]}
        >
          <Input placeholder="imagenet · coco · llama-3-8b" />
        </Form.Item>

        <Form.Item label="模式" name="mode" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio.Button value="ro">只读 (ro)</Radio.Button>
            <Radio.Button value="rw">读写 (rw)</Radio.Button>
          </Radio.Group>
        </Form.Item>

        <Form.Item label="授权对象" name="target_kind" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio.Button value="role">按角色</Radio.Button>
            <Radio.Button value="user">按用户</Radio.Button>
          </Radio.Group>
        </Form.Item>

        {targetKind === 'user' ? (
          <Form.Item
            label="用户"
            name="user_id"
            rules={[{ required: true, message: '请选择用户' }]}
          >
            <Select
              showSearch
              options={mockUsers.map((u) => ({
                value: u.id,
                label: `${u.displayName} (${u.email})`,
              }))}
              filterOption={(input, opt) =>
                (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
        ) : (
          <Form.Item
            label="角色"
            name="workspace_role"
            rules={[{ required: true, message: '请选择角色' }]}
          >
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        )}

        <Form.Item
          label={
            <Space>
              登记为数据集
              <Text type="secondary" style={{ fontSize: 12 }}>
                勾选后可在"数据集(快捷)" Tab 中直接看到
              </Text>
            </Space>
          }
          name="register_as_dataset"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        {registerAsDataset && (
          <>
            <Form.Item
              label="数据集名称"
              name="dataset_name"
              rules={[{ required: true, message: '请输入数据集名' }]}
            >
              <Input placeholder="e.g. imagenet-1k" />
            </Form.Item>
            <Form.Item label="描述" name="dataset_description">
              <Input.TextArea rows={2} placeholder="简要描述用途" />
            </Form.Item>
            <Form.Item label="README URL" name="readme_url">
              <Input placeholder="s3://... 或 https://..." />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  );
}

/* ============================================================================
 * Tab 3 · 数据集(快捷)
 * ========================================================================== */

interface DatasetsTabProps {
  permissionGroups: MockPermissionGroup[];
  pathGrants: MockPathGrant[];
  onOpenInPermissionGroups: (pgId: string, grantId: string) => void;
}

function DatasetsTab({
  permissionGroups,
  pathGrants,
  onOpenInPermissionGroups,
}: DatasetsTabProps) {
  const navigate = useNavigate();
  const datasets = useMemo(
    () => pathGrants.filter((g) => g.dataset_name !== null),
    [pathGrants],
  );

  const pgIndex = useMemo(() => {
    const m = new Map<string, MockPermissionGroup>();
    for (const pg of permissionGroups) m.set(pg.id, pg);
    return m;
  }, [permissionGroups]);

  return (
    <>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="📌 数据集 = 登记了名称的权限授权 · 新建数据集请去权限组 Tab 新增授权时勾选'登记为数据集'"
      />

      {datasets.length === 0 ? (
        <Empty description="暂无登记的数据集" />
      ) : (
        <Row gutter={[16, 16]}>
          {datasets.map((g) => {
            const pg = pgIndex.get(g.permission_group_id);
            return (
              <Col xs={24} md={12} xl={8} key={g.id}>
                <Card
                  hoverable
                  title={
                    <Space>
                      <DatabaseOutlined />
                      <span style={{ fontWeight: 600 }}>{g.dataset_name}</span>
                      <Tag color={g.mode === 'rw' ? 'orange' : 'green'}>
                        {g.mode.toUpperCase()}
                      </Tag>
                    </Space>
                  }
                  actions={[
                    <Button
                      key="goto"
                      type="link"
                      icon={<SafetyOutlined />}
                      onClick={() => onOpenInPermissionGroups(g.permission_group_id, g.id)}
                    >
                      去权限组查看
                    </Button>,
                    g.readme_url ? (
                      <Button
                        key="readme"
                        type="link"
                        icon={<FileTextOutlined />}
                        onClick={() => {
                          // External link — noop in mock.
                          message.info(`README: ${g.readme_url}`);
                        }}
                      >
                        README
                      </Button>
                    ) : (
                      <Tooltip key="readme" title="未提供 README">
                        <Button type="link" icon={<FileTextOutlined />} disabled>
                          README
                        </Button>
                      </Tooltip>
                    ),
                  ]}
                >
                  <Paragraph ellipsis={{ rows: 2 }} style={{ minHeight: 44 }}>
                    {g.dataset_description ?? (
                      <Text type="secondary">无描述</Text>
                    )}
                  </Paragraph>
                  <Descriptions size="small" column={1} colon>
                    <Descriptions.Item label="挂载路径">
                      <Text code style={{ fontSize: 12 }}>
                        {pg?.file_system_display_name ?? '-'}:{g.path}
                      </Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="大小">
                      {g.size_gb} GB · {prettyCount(g.file_count)} 文件
                    </Descriptions.Item>
                    <Descriptions.Item label="授权范围">
                      {g.user_id ? (
                        <Tag color="purple">👤 {g.user_display_name}</Tag>
                      ) : (
                        <Tag color="blue">🎭 {g.workspace_role}</Tag>
                      )}
                    </Descriptions.Item>
                    {g.readme_url && (
                      <Descriptions.Item label="README">
                        <AntLink
                          onClick={() => message.info(`README: ${g.readme_url}`)}
                        >
                          <LinkOutlined /> 查看
                        </AntLink>
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      <div style={{ marginTop: 16, textAlign: 'center' }}>
        <Button type="link" onClick={() => navigate('/admin/storage?tab=permission-groups')}>
          → 前往权限组 Tab 新建数据集授权
        </Button>
      </div>
    </>
  );
}
