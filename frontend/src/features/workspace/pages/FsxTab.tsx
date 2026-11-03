/**
 * Workspace 详情 · FSx 挂载 tab.
 *
 * - admin 可见: + 添加挂载 / 移除 / 授权成员 按钮
 * - 表格列: 挂载 ID / 描述 / 挂载点 / 子目录·gid / FSx ID / 容量 / 操作
 * - 授权: 每条挂载可给 ws 成员加 ro/rw 权限 (MountPermissions),
 *   成员有权限后才能在开发机上挂这个目录.
 *
 * 后端契约见 services/platform-api/app/modules/workspace/api/fsx_router.py
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  theme,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  DeleteOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { ApiError } from '@/shared/api';
import {
  attachFsx,
  detachFsx,
  grantMount,
  listFsxCandidates,
  listFsxDirectories,
  listMembers,
  listMountGrants,
  listWorkspaceFsx,
  listWsFsxCandidates,
  listWsMountableDirs,
  revokeMount,
  type FsxDirectory,
  type FsxFilesystemSummary,
  type MountAccess,
  type MountGrant,
  type WorkspaceFsxMount,
  type WorkspaceMember,
} from '@/features/workspace/api';

const { Text } = Typography;

interface FsxTabProps {
  wsId: string;
  isAdmin: boolean;
  /** 平台超管: 走原接口 (不筛 gid, 保留挂任意 gid 能力); 同时控制卸载按钮显隐. */
  isPlatformAdmin?: boolean;
  /** ws 固有主 gid (= runAsGroup). 第一次挂载固化, null 表示还没挂过. */
  primaryGid: number | null;
}

interface AttachFormValues {
  mount_id: string;
  description?: string;
  filesystem_id: string;
  /** 一级目录 (下拉) */
  top_dir: string;
  /** 可选的更深子路径 (手填), 如 train/proj-b */
  sub_path?: string;
  mount_path: string;
}

// mount_id 正则: 跟后端一致, 小写字母开头, 字母/数字/-, 3-40 字符
const MOUNT_ID_PATTERN = /^[a-z][a-z0-9-]{2,39}$/;
// 手填子路径: 字母/数字/_/-, 允许多级 /, 不允许开头/结尾 /
const SUB_PATH_PATTERN = /^[a-zA-Z0-9_-]+(\/[a-zA-Z0-9_-]+)*$/;

export default function FsxTab({
  wsId,
  isAdmin,
  isPlatformAdmin = false,
  primaryGid,
}: FsxTabProps) {
  const { t } = useTranslation(['workspace', 'common']);
  const { token } = theme.useToken();
  const [mounts, setMounts] = useState<WorkspaceFsxMount[]>([]);
  const [candidates, setCandidates] = useState<FsxFilesystemSummary[]>([]);
  const [directories, setDirectories] = useState<FsxDirectory[]>([]);
  const [loadingDirs, setLoadingDirs] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<AttachFormValues>();
  // 用户手动改过 mount_path 后, 不再被 mount_id 自动联动覆盖
  const mountPathTouched = useRef(false);

  // ===== 授权弹窗状态 =====
  const [grantMountTarget, setGrantMountTarget] =
    useState<WorkspaceFsxMount | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [grants, setGrants] = useState<MountGrant[]>([]);
  const [grantLoading, setGrantLoading] = useState(false);
  const [grantUsers, setGrantUsers] = useState<string[]>([]);
  const [grantAccess, setGrantAccess] = useState<MountAccess>('ro');
  const [grantSubmitting, setGrantSubmitting] = useState(false);

  const loadMounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listWorkspaceFsx(wsId);
      setMounts(list);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  const [loadingCandidates, setLoadingCandidates] = useState(false);

  const loadCandidatesIfNeeded = useCallback(async () => {
    if (!isAdmin) return;
    if (candidates.length > 0) return;
    setLoadingCandidates(true);
    try {
      // 平台超管走原接口 (不筛 gid); 非超管走 ws 级筛选接口 (只列 primary_gid 目录).
      const list = isPlatformAdmin
        ? await listFsxCandidates()
        : await listWsFsxCandidates(wsId);
      setCandidates(list);
    } catch {
      // 拉不到 modal 里会用 length===0 提示
    } finally {
      setLoadingCandidates(false);
    }
  }, [isAdmin, isPlatformAdmin, wsId, candidates.length]);

  useEffect(() => {
    void loadMounts();
  }, [loadMounts]);

  const handleOpenAttach = () => {
    form.resetFields();
    mountPathTouched.current = false;
    setDirectories([]);
    setModalOpen(true);
    void loadCandidatesIfNeeded();
  };

  // mount_id 输入时联动填 mount_path (= /fsx/<mount_id>), 除非用户已手动改过
  const handleMountIdChange = (mountId: string) => {
    if (mountPathTouched.current) return;
    form.setFieldsValue({ mount_path: mountId ? `/fsx/${mountId}` : '' });
  };

  const handleFilesystemChange = useCallback(
    async (filesystemId: string) => {
      form.setFieldsValue({ top_dir: undefined as unknown as string });
      setDirectories([]);
      if (!filesystemId) return;
      setLoadingDirs(true);
      try {
        // 平台超管走原接口 (列全部目录); 非超管走 ws 级接口 (只列 gid==primary_gid).
        const dirs = isPlatformAdmin
          ? await listFsxDirectories(filesystemId)
          : await listWsMountableDirs(wsId, filesystemId);
        setDirectories(dirs);
      } catch {
        setDirectories([]);
      } finally {
        setLoadingDirs(false);
      }
    },
    [form, isPlatformAdmin, wsId],
  );

  const handleAttach = async () => {
    try {
      const values = await form.validateFields();
      // 拼最终 subdir: 一级目录 + 可选手填子路径. gid 由后端探测.
      const sub = values.sub_path?.trim();
      const subdir = sub ? `${values.top_dir}/${sub}` : values.top_dir;
      setSubmitting(true);
      const list = await attachFsx(wsId, {
        mount_id: values.mount_id.trim(),
        description: values.description?.trim() || undefined,
        filesystem_id: values.filesystem_id,
        subdir,
        mount_path: values.mount_path.trim(),
      });
      setMounts(list);
      message.success(t('fsx.messages.attached'));
      setModalOpen(false);
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(e.message);
      } else if ((e as { errorFields?: unknown }).errorFields) {
        // form validation error - silent
      } else {
        message.error((e as Error).message || t('fsx.messages.attachFailed'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDetach = async (mount: WorkspaceFsxMount, force: boolean) => {
    try {
      const list = await detachFsx(wsId, mount.mount_id, force);
      setMounts(list);
      message.success(t('fsx.messages.detached'));
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409 && !force) {
          Modal.confirm({
            title: t('fsx.inUse.title'),
            content: t('fsx.inUse.content', { message: e.message }),
            okText: t('fsx.inUse.forceRemove'),
            okButtonProps: { danger: true },
            cancelText: t('common:actions.cancel'),
            onOk: () => handleDetach(mount, true),
          });
          return;
        }
        message.error(e.message);
      } else {
        message.error((e as Error).message || t('fsx.messages.detachFailed'));
      }
    }
  };

  // ===== 授权 =====
  const openGrantModal = useCallback(
    async (mount: WorkspaceFsxMount) => {
      setGrantMountTarget(mount);
      setGrantUsers([]);
      setGrantAccess('ro');
      setGrantLoading(true);
      try {
        const [mem, gr] = await Promise.all([
          listMembers(wsId),
          listMountGrants(wsId, mount.mount_id),
        ]);
        setMembers(mem);
        setGrants(gr);
      } catch (e) {
        message.error(
          e instanceof ApiError ? e.message : t('fsx.messages.loadGrantsFailed'),
        );
        setMembers([]);
        setGrants([]);
      } finally {
        setGrantLoading(false);
      }
    },
    [wsId, t],
  );

  const handleGrant = async () => {
    if (!grantMountTarget || grantUsers.length === 0) return;
    setGrantSubmitting(true);
    try {
      // 后端 grant 是单人接口, 多选时逐个授权; 拿最后一次返回的全量列表刷新.
      let updated: MountGrant[] = grants;
      for (const u of grantUsers) {
        updated = await grantMount(
          wsId,
          grantMountTarget.mount_id,
          u,
          grantAccess,
        );
      }
      setGrants(updated);
      setGrantUsers([]);
      message.success(t('fsx.messages.granted', { count: grantUsers.length }));
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : t('fsx.messages.grantFailed'));
    } finally {
      setGrantSubmitting(false);
    }
  };

  const handleRevoke = async (username: string) => {
    if (!grantMountTarget) return;
    try {
      const updated = await revokeMount(
        wsId,
        grantMountTarget.mount_id,
        username,
      );
      setGrants(updated);
      message.success(t('fsx.messages.revoked'));
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : t('fsx.messages.revokeFailed'));
    }
  };

  // 还没授权的成员 (下拉只列这些, 已授权的在列表里改/撤)
  const grantedUsernames = new Set(grants.map((g) => g.username));
  const grantableMembers = members.filter(
    (m) => !grantedUsernames.has(m.user_id),
  );

  // ws 主 gid: 优先用父组件传的 (DDB primary_gid); 刚挂第一个还没刷新时,
  // 用第一条挂载的 gid 兜底显示 (= 后端固化逻辑).
  const effectivePrimaryGid =
    primaryGid ?? mounts.find((m) => m.gid != null)?.gid ?? null;

  // 非超管 + 还没主 gid: 首次挂载需平台超管先固化 team gid 基线, 禁用挂载按钮.
  const blockFirstMount = !isPlatformAdmin && primaryGid == null;

  return (
    <div>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('fsx.intro')}
        </Text>
        {isAdmin && (
          <Tooltip
            title={
              blockFirstMount
                ? t('fsx.firstMountBlocked')
                : ''
            }
          >
            <span>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                disabled={blockFirstMount}
                onClick={handleOpenAttach}
              >
                {t('fsx.addButton')}
              </Button>
            </span>
          </Tooltip>
        )}
      </Space>

      {effectivePrimaryGid != null ? (
        <div
          style={{
            fontSize: 12,
            lineHeight: '20px',
            marginBottom: 16,
            color: token.colorTextTertiary,
          }}
        >
          <CheckCircleOutlined style={{ marginRight: 6, color: token.colorSuccess }} />
          {t('fsx.primaryGid.label')}{' '}
          <Text style={{ fontSize: 12, color: 'inherit' }}>{effectivePrimaryGid}</Text>
          <Tooltip title={t('fsx.primaryGid.tooltip')}>
            <InfoCircleOutlined style={{ marginLeft: 6, cursor: 'help' }} />
          </Tooltip>
        </div>
      ) : (
        <div
          style={{
            fontSize: 12,
            lineHeight: '20px',
            marginBottom: 16,
            color: token.colorWarning,
          }}
        >
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('fsx.primaryGid.unset')}
          <Tooltip title={t('fsx.primaryGid.unsetTooltip')}>
            <InfoCircleOutlined style={{ marginLeft: 6, cursor: 'help' }} />
          </Tooltip>
        </div>
      )}

      {error && (
        <Alert
          type="error"
          message={t('common:messages.loadFailed')}
          description={error}
          closable
          style={{ marginBottom: 16 }}
          onClose={() => setError(null)}
        />
      )}

      <Table<WorkspaceFsxMount>
        rowKey={(m) => m.mount_id || `${m.filesystem_id}::${m.subdir ?? ''}`}
        loading={loading}
        dataSource={mounts}
        pagination={false}
        locale={{ emptyText: t('fsx.empty') }}
        columns={[
          {
            title: t('fsx.columns.mountId'),
            dataIndex: 'mount_id',
            width: 150,
            render: (id: string) =>
              id ? (
                <Text strong style={{ fontFamily: 'monospace' }}>{id}</Text>
              ) : (
                <Text type="secondary">-</Text>
              ),
          },
          {
            title: t('common:fields.description'),
            dataIndex: 'description',
            ellipsis: { showTitle: false },
            render: (d: string) =>
              d ? (
                <Tooltip title={d}>
                  <Text>{d}</Text>
                </Tooltip>
              ) : (
                <Text type="secondary">-</Text>
              ),
          },
          {
            title: t('fsx.columns.mountPoint'),
            dataIndex: 'mount_path',
            width: 150,
            render: (p: string) => <Text code>{p}</Text>,
          },
          {
            title: t('fsx.columns.subdirGid'),
            width: 180,
            render: (_: unknown, m: WorkspaceFsxMount) =>
              m.subdir ? (
                <Text>
                  {m.subdir}{' '}
                  <Text type="secondary">· gid={m.gid ?? '-'}</Text>
                </Text>
              ) : (
                <Text type="secondary">-</Text>
              ),
          },
          {
            title: 'FSx ID',
            dataIndex: 'filesystem_id',
            width: 170,
            render: (id: string) => (
              <Tooltip title={id}>
                <Text code style={{ fontSize: 12 }}>{id}</Text>
              </Tooltip>
            ),
          },
          {
            title: t('common:fields.actions'),
            width: 180,
            render: (_: unknown, m: WorkspaceFsxMount) =>
              isAdmin ? (
                <Space size="small">
                  <Button
                    size="small"
                    icon={<TeamOutlined />}
                    onClick={() => void openGrantModal(m)}
                  >
                    {t('fsx.grant.action')}
                  </Button>
                  {/* 卸载保留平台超管 (后端 detach 也是 require_admin) */}
                  {isPlatformAdmin && (
                    <Popconfirm
                      title={t('fsx.removeConfirm.title')}
                      description={t('fsx.removeConfirm.description')}
                      okText={t('fsx.remove')}
                      okButtonProps={{ danger: true }}
                      cancelText={t('common:actions.cancel')}
                      onConfirm={() => handleDetach(m, false)}
                    >
                      <Button danger size="small" icon={<DeleteOutlined />}>
                        {t('fsx.remove')}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ) : null,
          },
        ]}
      />

      {/* ===== 添加 FSx 挂载弹窗 ===== */}
      <Modal
        title={t('fsx.addModal.title')}
        open={modalOpen}
        onOk={() => void handleAttach()}
        confirmLoading={submitting}
        onCancel={() => setModalOpen(false)}
        okText={t('fsx.addModal.ok')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
        width={520}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('fsx.addModal.hint')}
        />
        {loadingCandidates ? (
          <div style={{ textAlign: 'center', padding: '16px 0', marginBottom: 16 }}>
            <Spin tip={t('fsx.addModal.loadingCandidates')} />
          </div>
        ) : candidates.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('fsx.addModal.noCandidates')}
          />
        ) : null}
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="mount_id"
            label={t('fsx.columns.mountId')}
            tooltip={t('fsx.addModal.mountIdTooltip')}
            rules={[
              { required: true, message: t('fsx.addModal.mountIdRequired') },
              {
                pattern: MOUNT_ID_PATTERN,
                message: t('fsx.addModal.mountIdPattern'),
              },
            ]}
          >
            <Input
              placeholder={t('fsx.addModal.mountIdPlaceholder')}
              autoComplete="off"
              maxLength={40}
              onChange={(e) => handleMountIdChange(e.target.value.trim())}
            />
          </Form.Item>
          <Form.Item
            name="filesystem_id"
            label={t('fsx.addModal.filesystemLabel')}
            rules={[{ required: true, message: t('fsx.addModal.filesystemRequired') }]}
          >
            <Select
              placeholder={t('fsx.addModal.filesystemPlaceholder')}
              onChange={(v: string) => void handleFilesystemChange(v)}
              options={candidates.map((c) => ({
                value: c.filesystem_id,
                label: `${c.name} · ${(c.capacity_gib / 1024).toFixed(1)} TiB · ${c.filesystem_id}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="top_dir"
            label={t('fsx.addModal.topDirLabel')}
            tooltip={t('fsx.addModal.topDirTooltip')}
            rules={[{ required: true, message: t('fsx.addModal.topDirRequired') }]}
          >
            <Select
              placeholder={loadingDirs ? t('fsx.addModal.loading') : t('fsx.addModal.topDirPlaceholder')}
              loading={loadingDirs}
              disabled={directories.length === 0 && !loadingDirs}
              notFoundContent={
                loadingDirs ? t('fsx.addModal.loading') : t('fsx.addModal.topDirEmpty')
              }
              options={directories.map((d) => ({
                value: d.name,
                label: `/fsx/${d.name}  ·  gid=${d.gid}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="sub_path"
            label={t('fsx.addModal.subPathLabel')}
            tooltip={t('fsx.addModal.subPathTooltip')}
            rules={[
              {
                pattern: SUB_PATH_PATTERN,
                message: t('fsx.addModal.subPathPattern'),
              },
            ]}
          >
            <Input placeholder={t('fsx.addModal.subPathPlaceholder')} autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="mount_path"
            label={t('fsx.addModal.mountPathLabel')}
            tooltip={t('fsx.addModal.mountPathTooltip')}
            rules={[
              { required: true, message: t('fsx.addModal.mountPathRequired') },
              {
                pattern: /^\/[a-zA-Z0-9_/-]+$/,
                message: t('fsx.addModal.mountPathPattern'),
              },
            ]}
          >
            <Input
              placeholder={t('fsx.addModal.mountPathPlaceholder')}
              autoComplete="off"
              onChange={() => {
                mountPathTouched.current = true;
              }}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label={t('fsx.addModal.descriptionLabel')}
            tooltip={t('fsx.addModal.descriptionTooltip')}
            rules={[{ max: 200, message: t('fsx.addModal.descriptionMax') }]}
          >
            <Input.TextArea
              rows={2}
              maxLength={200}
              showCount
              placeholder={t('fsx.addModal.descriptionPlaceholder')}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* ===== 授权成员弹窗 ===== */}
      <Modal
        title={
          grantMountTarget
            ? t('fsx.grant.titleWithMount', {
                mountId: grantMountTarget.mount_id,
                mountPath: grantMountTarget.mount_path,
              })
            : t('fsx.grant.title')
        }
        open={grantMountTarget != null}
        onCancel={() => setGrantMountTarget(null)}
        footer={null}
        destroyOnClose
        width={560}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('fsx.grant.hint')}
        />
        {grantLoading ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <Spin tip={t('fsx.addModal.loading')} />
          </div>
        ) : (
          <>
            <div style={{ marginBottom: 16 }}>
              <Select
                mode="multiple"
                allowClear
                style={{ width: '100%', marginBottom: 8 }}
                placeholder={t('fsx.grant.memberPlaceholder')}
                value={grantUsers}
                onChange={(v) => setGrantUsers(v)}
                maxTagCount="responsive"
                optionFilterProp="label"
                notFoundContent={
                  grantableMembers.length === 0
                    ? t('fsx.grant.allGranted')
                    : undefined
                }
                options={grantableMembers.map((m) => ({
                  value: m.user_id,
                  label: m.display_name
                    ? `${m.display_name} (${m.user_id})`
                    : m.user_id,
                }))}
              />
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Select<MountAccess>
                  style={{ width: 140 }}
                  value={grantAccess}
                  onChange={(v) => setGrantAccess(v)}
                  options={[
                    { value: 'ro', label: t('fsx.grant.access.ro') },
                    { value: 'rw', label: t('fsx.grant.access.rw') },
                  ]}
                />
                <Button
                  type="primary"
                  disabled={grantUsers.length === 0}
                  loading={grantSubmitting}
                  onClick={() => void handleGrant()}
                >
                  {grantUsers.length > 0
                    ? t('fsx.grant.actionWithCount', { count: grantUsers.length })
                    : t('fsx.grant.action')}
                </Button>
              </Space>
            </div>

            <Table<MountGrant>
              rowKey="username"
              size="small"
              dataSource={grants}
              pagination={false}
              locale={{ emptyText: t('fsx.grant.empty') }}
              columns={[
                {
                  title: t('fsx.grant.columns.member'),
                  dataIndex: 'username',
                  render: (u: string) => (
                    <Text style={{ fontFamily: 'monospace' }}>{u}</Text>
                  ),
                },
                {
                  title: t('fsx.grant.columns.access'),
                  dataIndex: 'access',
                  width: 80,
                  render: (a: MountAccess) => (
                    <Tag color={a === 'rw' ? 'blue' : 'default'}>
                      {a === 'rw' ? t('fsx.grant.access.rw') : t('fsx.grant.access.ro')}
                    </Tag>
                  ),
                },
                {
                  title: t('common:fields.actions'),
                  width: 90,
                  render: (_: unknown, g: MountGrant) => (
                    <Popconfirm
                      title={t('fsx.grant.revokeConfirm')}
                      okText={t('fsx.grant.revoke')}
                      okButtonProps={{ danger: true }}
                      cancelText={t('common:actions.cancel')}
                      onConfirm={() => void handleRevoke(g.username)}
                    >
                      <Button danger size="small" icon={<DeleteOutlined />}>
                        {t('fsx.grant.revoke')}
                      </Button>
                    </Popconfirm>
                  ),
                },
              ]}
            />
          </>
        )}
      </Modal>
    </div>
  );
}
