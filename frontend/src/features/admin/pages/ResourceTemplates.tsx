import { useCallback, useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  message,
} from 'antd';
import {
  DownOutlined,
  InfoCircleOutlined,
  PlusOutlined,
  UpOutlined,
} from '@ant-design/icons';
import { ApiError } from '@/shared/api';
import PageDescription from '@/shared/ui/PageDescription';
import { useParams } from 'react-router-dom';
import { useAppStore } from '@/store';
import { listMembers } from '@/features/workspace/api';
import {
  createResourceTemplate,
  deleteResourceTemplate,
  listResourceTemplates,
  resourceText,
  updateResourceTemplate,
  type ResourceTemplateItem,
  type TemplateResource,
} from '@/api/resource-templates';

/**
 * 资源模版管理 — workspace 管理员维护统一资源模版 (GPU / CPU 核 / 内存 GiB)。
 * 2026-06-14 确定: 三类 (开发机/训练/推理) 共用一套模版, 不分类型。
 * 用户创建任务时只能选模版 (不能手填资源); 增删改仅 ws admin。
 */

export default function ResourceTemplates() {
  const { t } = useTranslation(['admin', 'common']);
  // wsId 取自路由 (workspaces/:wsId/resource-templates), 与业务页一致:
  // 顶栏切换工作空间 → URL 变 → useParams 变 → 页面跟随刷新。
  const { wsId = '' } = useParams();
  const currentUser = useAppStore((s) => s.currentUser);
  const isAdmin = currentUser?.is_admin ?? false;
  const [items, setItems] = useState<ResourceTemplateItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ResourceTemplateItem | null>(null);
  // 当前用户在该 ws 是否为 admin。增删改写权限 = 平台超管 OR ws role==admin,
  // 与后端 is_ws_admin 同口径 (services/.../resource_templates service 层写闸)。
  const [isWsAdmin, setIsWsAdmin] = useState(false);
  // 角色是否判定完成: 异步拉成员列表前别下"只读"结论 (否则 ws 管理员进页面会先
  // 闪一下只读/无新建按钮, 等成员列表回来才可编辑)。超管无需异步, 直接 resolved。
  const [roleResolved, setRoleResolved] = useState(false);
  const [tipOpen, setTipOpen] = useState(false);
  const [form] = Form.useForm();

  // 非超管时拉成员列表判断 role==admin (超管直通, 无需查)。复用 MainLayout 同款 pattern。
  useEffect(() => {
    if (isAdmin) {
      setIsWsAdmin(false);
      setRoleResolved(true); // 超管直通, 立即 resolved
      return;
    }
    if (!wsId) {
      setIsWsAdmin(false);
      setRoleResolved(true);
      return;
    }
    let cancelled = false;
    setRoleResolved(false);
    const myId = currentUser?.id;
    (async () => {
      try {
        const members = await listMembers(wsId);
        if (cancelled) return;
        const me = members.find((m) => m.user_id === myId);
        setIsWsAdmin(me?.role === 'admin');
      } catch {
        if (!cancelled) setIsWsAdmin(false); // 拉不到 → 保守按只读
      } finally {
        if (!cancelled) setRoleResolved(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [wsId, isAdmin, currentUser?.id]);

  // 写权限闸: 超管 OR 当前 ws 管理员。
  const canEdit = isAdmin || isWsAdmin;

  const load = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    listResourceTemplates(wsId)
      .then(setItems)
      .catch((err) => {
        const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
        message.error(t('shared.loadFailed', { error: msg }));
        setItems([]);
      })
      .finally(() => setLoading(false));
  }, [wsId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (row: ResourceTemplateItem) => {
    setEditing(row);
    // efa 老模板无此字段 → 回填 0, 编辑保存时补齐。
    form.setFieldsValue({
      name: row.name,
      description: row.description,
      ...row.resource,
      efa: row.resource.efa ?? 0,
    });
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const v = await form.validateFields();
    const resource: TemplateResource = {
      gpu: v.gpu,
      cpu_cores: v.cpu_cores,
      mem_gib: v.mem_gib,
      efa: v.efa ?? 0,
    };
    try {
      if (editing) {
        await updateResourceTemplate(wsId, editing.template_id, {
          name: v.name,
          description: v.description,
          resource,
        });
        message.success(t('resourceTemplates.updated'));
      } else {
        await createResourceTemplate(wsId, {
          name: v.name,
          description: v.description,
          resource,
        });
        message.success(t('resourceTemplates.created'));
      }
      setModalOpen(false);
      load();
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      message.error(t('shared.saveFailed', { error: msg }));
    }
  };

  const onDelete = async (row: ResourceTemplateItem) => {
    try {
      await deleteResourceTemplate(wsId, row.template_id);
      message.success(t('shared.deleted'));
      load();
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      message.error(t('shared.deleteFailed', { error: msg }));
    }
  };

  const columns = [
    { title: t('resourceTemplates.columns.name'), dataIndex: 'name', key: 'name' },
    { title: t('common:fields.description'), dataIndex: 'description', key: 'description', render: (d?: string) => d || '-' },
    {
      title: t('resourceTemplates.columns.resource'),
      key: 'resource',
      render: (_: unknown, row: ResourceTemplateItem) => resourceText(row.resource),
    },
    {
      title: t('common:fields.actions'),
      key: 'action',
      width: 140,
      render: (_: unknown, row: ResourceTemplateItem) => {
        // 角色判定未完成: 先显占位 (-), 别闪"只读" (否则 ws 管理员进来先看到只读)。
        if (!roleResolved) return <span style={{ color: 'rgba(0,0,0,0.25)' }}>-</span>;
        return canEdit ? (
          <Space>
            <a onClick={() => openEdit(row)}>{t('common:actions.edit')}</a>
            <Popconfirm
              title={t('resourceTemplates.deleteConfirm', { name: row.name })}
              onConfirm={() => onDelete(row)}
              okType="danger"
              okText={t('common:actions.delete')}
              cancelText={t('common:actions.cancel')}
            >
              <a style={{ color: '#f5222d' }}>{t('common:actions.delete')}</a>
            </Popconfirm>
          </Space>
        ) : (
          <Tag>{t('shared.readOnly')}</Tag>
        );
      },
    },
  ];

  return (
    <PageContainer
      header={{ title: t('resourceTemplates.title') }}
      extra={
        wsId && roleResolved && canEdit
          ? [
              <Button
                key="new"
                type="primary"
                icon={<PlusOutlined />}
                onClick={openCreate}
              >
                {t('resourceTemplates.newButton')}
              </Button>,
            ]
          : undefined
      }
    >
      <PageDescription>
        <Trans ns="admin" i18nKey="resourceTemplates.description" components={{ b: <b /> }} />
      </PageDescription>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('resourceTemplates.tipTitle')}
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
            {tipOpen ? <UpOutlined style={{ fontSize: 11 }} /> : <DownOutlined style={{ fontSize: 11 }} />}
          </a>
        }
        description={
          tipOpen ? (
            <div style={{ lineHeight: 1.8 }}>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>
                  <Trans ns="admin" i18nKey="resourceTemplates.tip1" components={{ b: <b /> }} />
                </li>
                <li>
                  <Trans ns="admin" i18nKey="resourceTemplates.tip2" components={{ b: <b /> }} />
                </li>
              </ul>
            </div>
          ) : null
        }
      />
      {!wsId && (
        <div
          style={{
            fontSize: 12,
            lineHeight: '20px',
            marginBottom: 16,
            color: 'rgba(0,0,0,0.45)',
          }}
        >
          <InfoCircleOutlined style={{ marginRight: 6 }} />
          {t('resourceTemplates.selectWsHint')}
        </div>
      )}
      <ProCard>
        <Table
          rowKey="template_id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={false}
          size="small"
        />
      </ProCard>

      <Modal
        title={editing ? t('resourceTemplates.modalEdit') : t('resourceTemplates.modalNew')}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={onSubmit}
        forceRender
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label={t('resourceTemplates.form.name')}
            rules={[{ required: true, message: t('shared.required') }]}
          >
            <Input placeholder={t('resourceTemplates.form.namePlaceholder')} />
          </Form.Item>
          <Form.Item name="description" label={t('common:fields.description')}>
            <Input placeholder={t('resourceTemplates.form.descriptionPlaceholder')} />
          </Form.Item>
          <Space>
            <Form.Item name="gpu" label={t('resourceTemplates.form.gpu')} rules={[{ required: true }]}>
              <InputNumber min={0} max={8} style={{ width: '100%' }} />
            </Form.Item>
            {/* EFA 网卡数: 多节点 GPU 训练 RDMA 用; 默认 0 (开发机/推理及单机训练填 0)。 */}
            <Form.Item
              name="efa"
              label={t('resourceTemplates.form.efa')}
              initialValue={0}
              tooltip={t('resourceTemplates.form.efaTip')}
              rules={[{ required: true }]}
            >
              <InputNumber min={0} step={1} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space>
            <Form.Item name="cpu_cores" label={t('resourceTemplates.form.cpu')} rules={[{ required: true }]}>
              <InputNumber min={0.5} step={1} addonAfter={t('resourceTemplates.form.cpuUnit')} />
            </Form.Item>
            <Form.Item name="mem_gib" label={t('resourceTemplates.form.memory')} rules={[{ required: true }]}>
              <InputNumber min={0.5} step={1} addonAfter="GiB" />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </PageContainer>
  );
}
