import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Table,
  Typography,
  message,
} from 'antd';
import { KeyOutlined, PlusOutlined } from '@ant-design/icons';
import PageDescription from '@/shared/ui/PageDescription';
import { ApiError } from '@/shared/api';
import { deleteSecretKey, getSecretView, putSecretKey } from '@/api/secret';

const { Text } = Typography;

/**
 * Secret 管理 (工作空间级, · B2 每人一把)。
 * 每人管自己的 key-value 凭证 (token/密码/API key 等); secret 名平台自动派生 (无感)。
 * value 保存后不回显 (仿 PAT); 列表只显 key 名。训练环境变量 secretKeyRef 注入。
 */
export default function TokenHub() {
  const { t } = useTranslation(['secret', 'common']);
  const { wsId = '' } = useParams();
  const [keys, setKeys] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<{ key: string; value: string }>();

  const refresh = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    getSecretView(wsId)
      .then((v) => setKeys(v.keys))
      .catch((err) => {
        message.error(err instanceof ApiError ? err.message : t('loadFailed'));
        setKeys([]);
      })
      .finally(() => setLoading(false));
  }, [wsId, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handlePut = async () => {
    const v = await form.validateFields();
    setSubmitting(true);
    try {
      const view = await putSecretKey(wsId, { key: v.key.trim(), value: v.value });
      setKeys(view.keys);
      message.success(t('saved'));
      setModalOpen(false);
      form.resetFields();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('saveFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (key: string) => {
    try {
      const view = await deleteSecretKey(wsId, key);
      setKeys(view.keys);
      message.success(t('deleted'));
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('deleteFailed'));
    }
  };

  const columns = [
    {
      title: t('columns.key'),
      dataIndex: 'key',
      render: (v: string) => (
        <Text style={{ fontFamily: 'monospace', fontSize: 13 }}>{v}</Text>
      ),
    },
    {
      title: t('columns.value'),
      key: 'value',
      width: 120,
      render: () => <Text type="secondary">••••••••</Text>,
    },
    {
      title: t('common:fields.actions'),
      key: 'action',
      width: 90,
      render: (_: unknown, row: { key: string }) => (
        <Popconfirm
          title={t('deleteConfirm', { key: row.key })}
          description={t('deleteDesc')}
          onConfirm={() => handleDelete(row.key)}
          okType="danger"
          okText={t('common:actions.delete')}
          cancelText={t('common:actions.cancel')}
        >
          <a style={{ color: '#f5222d' }}>{t('common:actions.delete')}</a>
        </Popconfirm>
      ),
    },
  ];

  return (
    <PageContainer
      header={{ title: t('title') }}
      extra={[
        <Button
          key="add"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setModalOpen(true)}
        >
          {t('addButton')}
        </Button>,
      ]}
    >
      <PageDescription>
        <Trans ns="secret" i18nKey="description" components={{ b: <b /> }} />
      </PageDescription>

      <ProCard>
        <Table
          rowKey="key"
          loading={loading}
          columns={columns}
          dataSource={keys.map((k) => ({ key: k }))}
          pagination={false}
          size="small"
        />
      </ProCard>

      <Alert
        type="info"
        showIcon
        icon={<KeyOutlined />}
        style={{ marginTop: 16 }}
        message={<span style={{ fontSize: 13 }}>{t('howTitle')}</span>}
        description={
          <span style={{ fontSize: 12 }}>
            {t('howDesc')}
          </span>
        }
      />

      <Modal
        title={t('modalTitle')}
        open={modalOpen}
        onOk={handlePut}
        confirmLoading={submitting}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
        }}
        okText={t('common:actions.save')}
        cancelText={t('common:actions.cancel')}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item
            name="key"
            label={t('form.keyLabel')}
            rules={[{ required: true, message: t('form.keyRequired') }]}
            extra={t('form.keyExtra')}
          >
            <Input placeholder="GITHUB_TOKEN" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="value"
            label={t('form.valueLabel')}
            rules={[{ required: true, message: t('form.valueRequired') }]}
            extra={t('form.valueExtra')}
          >
            <Input.Password placeholder={t('form.valuePlaceholder')} autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
