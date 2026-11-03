/**
 * Workspace 详情 · S3 挂载 tab.
 *
 * - admin 可见: + 添加挂载 + 移除按钮
 * - 表格列: 挂载点 / Bucket / Prefix / Region / 操作
 * - 默认读写, 但 Mountpoint 限制多 (rename / fsync 后续写 / random write 不支持).
 *   用户写 PyTorch checkpoint 等场景应走 boto3 SDK, 不走挂载点.
 *
 * 后端契约见 services/platform-api/app/modules/workspace/api/s3_router.py
 */
import { useCallback, useEffect, useState } from 'react';
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
  Tooltip,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { ApiError } from '@/shared/api';
import {
  attachS3,
  detachS3,
  listWsS3BucketCandidates,
  listWorkspaceS3,
  type S3BucketSummary,
  type WorkspaceS3Mount,
} from '@/features/workspace/api';

const { Text } = Typography;

interface S3TabProps {
  wsId: string;
  isAdmin: boolean;
}

interface AttachFormValues {
  mount_id: string;
  description?: string;
  bucket_name: string;
  mount_path: string;
  prefix?: string;
}

// mount_id 正则: 跟后端一致, 小写字母开头, 字母/数字/-, 3-40 字符
const MOUNT_ID_PATTERN = /^[a-z][a-z0-9-]{2,39}$/;

export default function S3Tab({ wsId, isAdmin }: S3TabProps) {
  const { t } = useTranslation(['workspace', 'common']);
  const [mounts, setMounts] = useState<WorkspaceS3Mount[]>([]);
  const [candidates, setCandidates] = useState<S3BucketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<AttachFormValues>();

  const loadMounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listWorkspaceS3(wsId);
      setMounts(list);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [wsId]);

  const [loadingCandidates, setLoadingCandidates] = useState(false);

  // 候选池仅在 "添加 S3 挂载" Modal 打开时才拉 (列表 Tab 不需要 · 减少
  // 首屏 AWS s3:list 调用)
  const loadCandidatesIfNeeded = useCallback(async () => {
    if (!isAdmin) return;
    if (candidates.length > 0) return; // 已经拉过, 不重复
    setLoadingCandidates(true);
    try {
      const list = await listWsS3BucketCandidates(wsId);
      setCandidates(list);
    } catch {
      // 拉不到 modal 里会用 length===0 提示
    } finally {
      setLoadingCandidates(false);
    }
  }, [isAdmin, candidates.length, wsId]);

  useEffect(() => {
    void loadMounts();
  }, [loadMounts]);

  const handleOpenAttach = () => {
    form.resetFields();
    setModalOpen(true);
    void loadCandidatesIfNeeded();
  };

  const handleAttach = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const list = await attachS3(wsId, {
        mount_id: values.mount_id.trim(),
        description: values.description?.trim() || undefined,
        bucket_name: values.bucket_name,
        mount_path: values.mount_path.trim(),
        prefix: values.prefix?.trim() || undefined,
      });
      setMounts(list);
      message.success(t('s3.messages.attached'));
      setModalOpen(false);
    } catch (e) {
      if (e instanceof ApiError) {
        message.error(e.message);
      } else if ((e as { errorFields?: unknown }).errorFields) {
        // form validation - silent
      } else {
        message.error((e as Error).message || t('s3.messages.attachFailed'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDetach = async (mount: WorkspaceS3Mount, force: boolean) => {
    try {
      const list = await detachS3(wsId, mount.mount_id, force);
      setMounts(list);
      message.success(t('s3.messages.detached'));
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409 && !force) {
          Modal.confirm({
            title: t('s3.inUse.title'),
            content: t('s3.inUse.content', { message: e.message }),
            okText: t('s3.inUse.forceRemove'),
            okButtonProps: { danger: true },
            cancelText: t('common:actions.cancel'),
            onOk: () => handleDetach(mount, true),
          });
          return;
        }
        message.error(e.message);
      } else {
        message.error((e as Error).message || t('s3.messages.detachFailed'));
      }
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t('s3.intro')}
        </Text>
        {isAdmin && (
          <Button type="primary" icon={<PlusOutlined />} onClick={handleOpenAttach}>
            {t('s3.addButton')}
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

      <Table<WorkspaceS3Mount>
        rowKey={(m) => m.mount_id || `${m.bucket_name}::${m.prefix ?? ''}`}
        loading={loading}
        dataSource={mounts}
        pagination={false}
        locale={{ emptyText: t('s3.empty') }}
        columns={[
          {
            title: t('s3.columns.mountId'),
            dataIndex: 'mount_id',
            width: 160,
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
            title: t('s3.columns.mountPoint'),
            dataIndex: 'mount_path',
            width: 160,
            render: (p: string) => <Text code>{p}</Text>,
          },
          {
            title: 'Bucket',
            dataIndex: 'bucket_name',
            width: 200,
            render: (b: string, m: WorkspaceS3Mount) => (
              <Tooltip title={`${b} · ${m.region}`}>
                <Text code style={{ fontSize: 12 }}>{b}</Text>
              </Tooltip>
            ),
          },
          {
            title: 'Prefix',
            dataIndex: 'prefix',
            width: 160,
            render: (p: string) =>
              p ? <Text code style={{ fontSize: 12 }}>{p}</Text> : <Text type="secondary">-</Text>,
          },
          {
            title: t('common:fields.actions'),
            width: 100,
            render: (_: unknown, m: WorkspaceS3Mount) =>
              isAdmin ? (
                <Popconfirm
                  title={t('s3.removeConfirm.title')}
                  description={t('s3.removeConfirm.description')}
                  okText={t('s3.remove')}
                  okButtonProps={{ danger: true }}
                  cancelText={t('common:actions.cancel')}
                  onConfirm={() => handleDetach(m, false)}
                >
                  <Button danger size="small" icon={<DeleteOutlined />}>
                    {t('s3.remove')}
                  </Button>
                </Popconfirm>
              ) : null,
          },
        ]}
      />

      <Modal
        title={t('s3.addModal.title')}
        open={modalOpen}
        onOk={() => void handleAttach()}
        confirmLoading={submitting}
        onCancel={() => setModalOpen(false)}
        okText={t('s3.addModal.ok')}
        cancelText={t('common:actions.cancel')}
        destroyOnClose
        width={560}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('s3.addModal.hint')}
        />
        {loadingCandidates ? (
          <div style={{ textAlign: 'center', padding: '16px 0', marginBottom: 16 }}>
            <Spin tip={t('s3.addModal.loadingCandidates')} />
          </div>
        ) : candidates.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('s3.addModal.noCandidates')}
          />
        ) : null}
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="mount_id"
            label={t('s3.columns.mountId')}
            tooltip={t('s3.addModal.mountIdTooltip')}
            rules={[
              { required: true, message: t('s3.addModal.mountIdRequired') },
              {
                pattern: MOUNT_ID_PATTERN,
                message: t('s3.addModal.mountIdPattern'),
              },
            ]}
          >
            <Input
              placeholder={t('s3.addModal.mountIdPlaceholder')}
              autoComplete="off"
              maxLength={40}
            />
          </Form.Item>
          <Form.Item
            name="bucket_name"
            label="S3 Bucket"
            rules={[{ required: true, message: t('s3.addModal.bucketRequired') }]}
          >
            <Select
              placeholder={t('s3.addModal.bucketPlaceholder')}
              options={candidates.map((c) => ({
                value: c.bucket_name,
                label: `${c.name} · ${c.bucket_name} (${c.region})`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="prefix"
            label={t('s3.addModal.prefixLabel')}
            tooltip={t('s3.addModal.prefixTooltip')}
          >
            <Input placeholder="datasets/imagenet/" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="mount_path"
            label={t('s3.addModal.mountPathLabel')}
            tooltip={t('s3.addModal.mountPathTooltip')}
            rules={[
              { required: true, message: t('s3.addModal.mountPathRequired') },
              {
                pattern: /^\/[a-zA-Z0-9_/-]+$/,
                message: t('s3.addModal.mountPathPattern'),
              },
            ]}
          >
            <Input placeholder="/s3/imagenet" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="description"
            label={t('s3.addModal.descriptionLabel')}
            tooltip={t('s3.addModal.descriptionTooltip')}
            rules={[{ max: 200, message: t('s3.addModal.descriptionMax') }]}
          >
            <Input.TextArea
              rows={2}
              maxLength={200}
              showCount
              placeholder={t('s3.addModal.descriptionPlaceholder')}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
