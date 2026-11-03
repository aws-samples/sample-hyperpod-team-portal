/**
 * Workspace 详情 · 成员 tab.
 *
 * 角色两种 (admin/member):
 *   - admin:  workspace 管理员, 能加/减成员, 调队列优先级
 *   - member: 普通成员, 能创建任务/开发机
 *
 * 仅 platform admin (is_admin) 可见添加/修改/删除按钮.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Form,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';
import {
  addMember,
  listMembers,
  removeMember,
  searchWsIdcUsers,
  updateMemberRole,
  type WorkspaceMember,
  type WorkspaceRole,
} from '@/features/workspace/api';
import { type IdcUserSummary } from '@/api/user';

const { Text } = Typography;

interface MembersTabProps {
  wsId: string;
  isAdmin: boolean;
}

interface AddFormValues {
  user_id: string;
  role: WorkspaceRole;
}

/** 角色选项: label 存 key, 渲染时再翻译。 */
const ROLE_OPTIONS: { value: WorkspaceRole; labelKey: 'members.roles.admin' | 'members.roles.member' }[] = [
  { value: 'admin', labelKey: 'members.roles.admin' },
  { value: 'member', labelKey: 'members.roles.member' },
];

const roleColor = (r: string): string =>
  r === 'admin' ? 'gold' : 'blue';

export default function MembersTab({ wsId, isAdmin }: MembersTabProps) {
  const { t } = useTranslation(['workspace', 'common']);
  const roleLabel = (r: string): string => {
    const opt = ROLE_OPTIONS.find((o) => o.value === r);
    return opt ? t(opt.labelKey) : r;
  };
  const roleOptions = ROLE_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }));
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<AddFormValues>();
  const [editing, setEditing] = useState<WorkspaceMember | null>(null);

  // 当前登录用户 id (= IdC username), 与成员行 member.user_id 同源可比.
  // 用于禁用"操作自己"的移除/降级 (后端已 403 兜底, 这里只做体验优化).
  const currentUserId = useAppStore((s) => s.currentUser?.id);

  // IdC 搜索状态 (加成员 Modal 用)
  const [idcOptions, setIdcOptions] = useState<IdcUserSummary[]>([]);
  const [idcSearching, setIdcSearching] = useState(false);
  const idcDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idcLastQueryRef = useRef<string>('');

  const handleIdcSearch = useCallback((q: string) => {
    // debounce 300ms · 后端走 IdC GetUserId 精确等值, 部分输入查不到很正常
    if (idcDebounceRef.current) clearTimeout(idcDebounceRef.current);
    const trimmed = q.trim();
    if (!trimmed) {
      setIdcOptions([]);
      setIdcSearching(false);
      return;
    }
    idcDebounceRef.current = setTimeout(async () => {
      idcLastQueryRef.current = trimmed;
      setIdcSearching(true);
      try {
        const list = await searchWsIdcUsers(wsId, trimmed);
        // 过期响应丢弃 (用户又输了新字)
        if (idcLastQueryRef.current !== trimmed) return;
        setIdcOptions(list);
      } catch {
        if (idcLastQueryRef.current !== trimmed) return;
        setIdcOptions([]);
      } finally {
        if (idcLastQueryRef.current === trimmed) setIdcSearching(false);
      }
    }, 300);
  }, [wsId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listMembers(wsId);
      setMembers(list);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAdd = async () => {
    try {
      const v = await form.validateFields();
      setSubmitting(true);
      await addMember(wsId, {
        user_id: v.user_id.trim(),
        role: v.role,
      });
      message.success(t('members.messages.added'));
      setAddOpen(false);
      void load();
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(e.message);
      } else if ((e as { errorFields?: unknown }).errorFields) {
        // form validation - silent
      } else {
        message.error((e as Error).message || t('members.messages.addFailed'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateRole = async (m: WorkspaceMember, role: WorkspaceRole) => {
    try {
      await updateMemberRole(wsId, m.user_id, role);
      message.success(t('members.messages.roleChanged', { role: roleLabel(role) }));
      setEditing(null);
      void load();
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(e.message);
      } else {
        message.error((e as Error).message || t('members.messages.updateFailed'));
      }
    }
  };

  const handleRemove = async (m: WorkspaceMember) => {
    try {
      await removeMember(wsId, m.user_id);
      message.success(t('members.messages.removed'));
      void load();
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(e.message);
      } else {
        message.error((e as Error).message || t('members.messages.removeFailed'));
      }
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Text type="secondary">
          {t('members.intro')}
        </Text>
        {isAdmin && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
            {t('members.addButton')}
          </Button>
        )}
      </Space>

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

      <Table<WorkspaceMember>
        rowKey="user_id"
        loading={loading}
        dataSource={members}
        pagination={false}
        locale={{ emptyText: t('members.empty') }}
        columns={[
          {
            title: t('members.columns.username'),
            dataIndex: 'user_id',
            render: (u: string) => <Text code>{u}</Text>,
          },
          {
            title: t('members.columns.email'),
            dataIndex: 'email',
            render: (e: string) => e || <Text type="secondary">-</Text>,
          },
          {
            title: t('members.columns.role'),
            dataIndex: 'role',
            width: 180,
            render: (_: unknown, m: WorkspaceMember) => {
              if (editing?.user_id === m.user_id && isAdmin) {
                const isSelf = m.user_id === currentUserId;
                // 自己不能降级为成员 → 禁用 member 选项 (升级为管理员不限制).
                const roleSelectOptions = roleOptions.map((o) =>
                  isSelf && o.value === 'member'
                    ? { ...o, label: t('members.selfDisabledOption', { role: o.label }), disabled: true }
                    : o,
                );
                return (
                  <Space>
                    <Select
                      value={m.role}
                      style={{ width: 220 }}
                      onChange={(v) => void handleUpdateRole(m, v)}
                      options={roleSelectOptions}
                    />
                    <Button size="small" onClick={() => setEditing(null)}>
                      {t('common:actions.cancel')}
                    </Button>
                  </Space>
                );
              }
              return <Tag color={roleColor(m.role)}>{roleLabel(m.role)}</Tag>;
            },
          },
          {
            title: t('members.columns.joinedAt'),
            dataIndex: 'joined_at',
            width: 180,
            render: (joinedAt: string) => joinedAt || '-',
          },
          {
            title: t('common:fields.actions'),
            width: 160,
            render: (_: unknown, m: WorkspaceMember) => {
              if (!isAdmin) return null;
              const isSelf = m.user_id === currentUserId;
              return (
                <Space>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => setEditing(m)}
                  >
                    {t('members.changeRole')}
                  </Button>
                  {isSelf ? (
                    // 自己不能移除自己 (后端 403 兜底); disabled Button 不冒泡 hover, 用 span 包裹.
                    <Tooltip title={t('members.cannotActOnSelf')}>
                      <span>
                        <Button danger size="small" disabled icon={<DeleteOutlined />} />
                      </span>
                    </Tooltip>
                  ) : (
                    <Popconfirm
                      title={t('members.removeConfirm', { userId: m.user_id })}
                      okText={t('members.remove')}
                      okButtonProps={{ danger: true }}
                      cancelText={t('common:actions.cancel')}
                      onConfirm={() => handleRemove(m)}
                    >
                      <Button danger size="small" icon={<DeleteOutlined />} />
                    </Popconfirm>
                  )}
                </Space>
              );
            },
          },
        ]}
      />

      <Modal
        title={t('members.addModal.title')}
        open={addOpen}
        onOk={() => void handleAdd()}
        confirmLoading={submitting}
        onCancel={() => setAddOpen(false)}
        okText={t('members.addModal.ok')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
        width={480}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('members.addModal.hint')}
        />
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ role: 'member' }}
        >
          <Form.Item
            name="user_id"
            label={t('members.addModal.userLabel')}
            rules={[{ required: true, message: t('members.addModal.userRequired') }]}
          >
            <Select<string>
              showSearch
              placeholder={t('members.addModal.userPlaceholder')}
              filterOption={false}
              onSearch={handleIdcSearch}
              notFoundContent={
                idcSearching ? <Spin size="small" /> : <span>{t('members.addModal.userNotFound')}</span>
              }
              options={idcOptions.map((u) => ({
                value: u.username,
                label: (
                  <span>
                    <b>{u.display_name}</b>
                    <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                      {u.email} · {u.username}
                    </Text>
                  </span>
                ),
              }))}
            />
          </Form.Item>
          <Form.Item
            name="role"
            label={t('members.columns.role')}
            rules={[{ required: true, message: t('members.addModal.roleRequired') }]}
          >
            <Select options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
