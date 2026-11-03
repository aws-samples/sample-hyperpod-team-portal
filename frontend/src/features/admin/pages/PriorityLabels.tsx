import { useCallback, useEffect, useRef, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import PageDescription from '@/shared/ui/PageDescription';
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
import { DownOutlined, PlusOutlined, UpOutlined } from '@ant-design/icons';
import { ApiError } from '@/shared/api';
import { useAppStore } from '@/store';
import {
  createPriorityClass,
  deletePriorityClass,
  listPriorityClasses,
  updatePriorityClass,
  type PriorityClassItem,
} from '@/api/priority';

/**
 * 优先级 label 管理 (仅平台超管).
 * 抢占开关 (per-ws ClusterQueue) 已拆到独立页面 WorkspacePreemption.tsx.
 */

// ============ tab1: 优先级档位 ============
// onCreateRef: 父组件持有 openCreate 句柄, 把"新建档位"按钮提到 PageContainer extra 与其他页面对齐布局。
function PriorityClassTab({
  isAdmin,
  onCreateRef,
}: {
  isAdmin: boolean;
  onCreateRef: { current: (() => void) | null };
}) {
  const { t } = useTranslation(['admin', 'common']);
  const [items, setItems] = useState<PriorityClassItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState<PriorityClassItem | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(() => {
    setLoading(true);
    listPriorityClasses()
      // 默认按优先级值降序展示, 不依赖列的 defaultSortOrder (会让整列变灰底)
      .then((list) => setItems([...list].sort((a, b) => b.value - a.value)))
      .catch((err) => {
        const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
        message.error(t('shared.loadFailed', { error: msg }));
      })
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = useCallback(() => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  }, [form]);

  // 注册 openCreate 给父组件 (mount 后, unmount 清掉避免悬挂引用)。
  useEffect(() => {
    onCreateRef.current = openCreate;
    return () => {
      onCreateRef.current = null;
    };
  }, [onCreateRef, openCreate]);
  const openEdit = (row: PriorityClassItem) => {
    setEditing(row);
    setModalOpen(true);
  };

  const onSubmit = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    try {
      if (editing) {
        await updatePriorityClass(editing.name, { value: v.value });
        message.success(t('priorityLabels.updated'));
      } else {
        await createPriorityClass({ name: v.name, value: v.value });
        message.success(t('priorityLabels.created'));
      }
      setModalOpen(false);
      load();
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      message.error(t('shared.saveFailed', { error: msg }));
    } finally {
      setSubmitting(false);
    }
  };

  const onDelete = async (row: PriorityClassItem) => {
    try {
      await deletePriorityClass(row.name);
      message.success(t('shared.deleted'));
      load();
    } catch (err) {
      const msg = err instanceof ApiError ? `${err.status} ${err.message}` : String(err);
      message.error(t('shared.deleteFailed', { error: msg }));
    }
  };

  const columns = [
    {
      title: t('priorityLabels.columns.name'),
      dataIndex: 'name',
      key: 'name',
      // 档位名 Tag 样式与任务总览的「优先级档位」列保持一致 (浅橙)
      render: (v: string) => <Tag color="orange">{v}</Tag>,
    },
    {
      title: t('priorityLabels.columns.weight'),
      dataIndex: 'value',
      key: 'value',
      // 不再设 defaultSortOrder (会让整列变灰底提示"当前排序列");
      // 改成手动按 value 降序填 dataSource, 视觉上保持普通列样式。
      sorter: (a: PriorityClassItem, b: PriorityClassItem) => a.value - b.value,
      render: (v: number) => (
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>
      ),
    },
    { title: t('common:fields.description'), dataIndex: 'description', key: 'description', render: (d?: string) => d || '-' },
    {
      title: t('common:fields.actions'),
      key: 'action',
      width: 130,
      render: (_: unknown, row: PriorityClassItem) =>
        isAdmin ? (
          <Space>
            <a onClick={() => openEdit(row)}>{t('common:actions.edit')}</a>
            <Popconfirm
              title={t('priorityLabels.deleteConfirm', { name: row.name })}
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
        ),
    },
  ];

  return (
    <>
      <Table
        rowKey="name"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
        size="small"
      />
      <Modal
        title={editing ? t('priorityLabels.modalEdit') : t('priorityLabels.modalNew')}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={onSubmit}
        confirmLoading={submitting}
        maskClosable={!submitting}
        cancelButtonProps={{ disabled: submitting }}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={editing ? { name: editing.name, value: editing.value } : {}}
        >
          <Form.Item
            name="name"
            label={t('priorityLabels.form.nameLabel')}
            rules={[
              { required: true, message: t('shared.required') },
              { pattern: /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, message: t('priorityLabels.form.namePattern') },
              { max: 40, message: t('priorityLabels.form.nameMax') },
            ]}
          >
            <Input placeholder="urgent" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="value" label={t('priorityLabels.form.weightLabel')} rules={[{ required: true }]}>
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default function PriorityLabels() {
  const { t } = useTranslation(['admin', 'common']);
  const isAdmin = useAppStore((s) => s.currentUser?.is_admin ?? false);
  // 子组件注册 openCreate 句柄, 父组件把"新建优先级档位"按钮放到 PageContainer extra
  const createRef = useRef<(() => void) | null>(null);
  const [tipOpen, setTipOpen] = useState(false);
  return (
    <PageContainer
      header={{ title: t('priorityLabels.title') }}
      extra={
        isAdmin
          ? [
              <Button
                key="new"
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => createRef.current?.()}
              >
                {t('priorityLabels.newButton')}
              </Button>,
            ]
          : undefined
      }
    >
      <PageDescription>{t('priorityLabels.description')}</PageDescription>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('priorityLabels.tipTitle')}
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
                  <Trans ns="admin" i18nKey="priorityLabels.tip1" components={{ b: <b /> }} />{/* gitleaks:allow */}
                </li>
                <li>{t('priorityLabels.tip2')}</li>
                <li>
                  <Trans ns="admin" i18nKey="priorityLabels.tip3" components={{ b: <b /> }} />{/* gitleaks:allow */}
                </li>
                <li>
                  <Trans ns="admin" i18nKey="priorityLabels.tip4" components={{ b: <b /> }} />{/* gitleaks:allow */}
                </li>
              </ul>
            </div>
          ) : null
        }
      />
      {!isAdmin && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('shared.readOnlyMode')}
          description={t('priorityLabels.readOnlyDesc')}
        />
      )}
      <ProCard>
        <PriorityClassTab isAdmin={isAdmin} onCreateRef={createRef} />
      </ProCard>
    </PageContainer>
  );
}
