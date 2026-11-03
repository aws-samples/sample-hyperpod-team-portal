/**
 * 个人 API Token 管理 Modal。
 * 三态: 无 token (生成表单) / 刚生成 (明文一次性展示) / 有 token (展示+删除)。
 * 每人一把: 有 token 时'生成'禁用, 必须先删。
 */
import { useEffect, useState } from 'react';
import {
  Alert, Button, Checkbox, DatePicker, Descriptions, Modal,
  Popconfirm, Space, Typography, message,
} from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { useTranslation } from 'react-i18next';
import {
  type ApiTokenStatus, createMyApiToken, deleteMyApiToken, getMyApiToken,
} from '@/api/apiToken';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ApiTokenModal({ open, onClose }: Props) {
  const { t } = useTranslation('common');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<ApiTokenStatus | null>(null);
  const [neverExpire, setNeverExpire] = useState(false);
  const [expiresAt, setExpiresAt] = useState<Dayjs | null>(null);
  const [plainToken, setPlainToken] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      setStatus(await getMyApiToken());
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setPlainToken(null);
      setNeverExpire(false);
      setExpiresAt(null);
      void refresh();
    }
  }, [open]);

  const handleCreate = async () => {
    if (!neverExpire && !expiresAt) {
      message.warning(t('apiToken.expiryRequired'));
      return;
    }
    setLoading(true);
    try {
      const created = await createMyApiToken({
        never_expire: neverExpire,
        expires_at: neverExpire ? null : expiresAt?.toISOString() ?? null,
      });
      setPlainToken(created.token);
      await refresh();
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setLoading(true);
    try {
      await deleteMyApiToken();
      setPlainToken(null);
      await refresh();
    } finally {
      setLoading(false);
    }
  };

  const copyToken = async () => {
    if (plainToken) {
      await navigator.clipboard.writeText(plainToken);
      message.success(t('messages.copied'));
    }
  };

  const hasToken = status?.exists === true;

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="API Token" width={620}>
      {/* 刚生成: 明文一次性展示 */}
      {plainToken && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert
            type="warning" showIcon
            message={t('apiToken.copyNow')}
          />
          <Typography.Paragraph
            copyable={{ text: plainToken, icon: <CopyOutlined /> }}
            code style={{ wordBreak: 'break-all', fontSize: 14 }}
          >
            {plainToken}
          </Typography.Paragraph>
          <Alert
            type="info"
            message={t('apiToken.curlUsage')}
            description={
              <Typography.Text code style={{ whiteSpace: 'pre-wrap' }}>
                {`curl -H "Authorization: Bearer ${plainToken}" \\\n  https://<your-host>/api/v1/training/jobs`}
              </Typography.Text>
            }
          />
          <Button onClick={copyToken} icon={<CopyOutlined />}>{t('apiToken.copyAgain')}</Button>
        </Space>
      )}

      {/* 已有 token (且非刚生成态) */}
      {!plainToken && hasToken && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Token">{status?.token_display}</Descriptions.Item>
            <Descriptions.Item label={t('fields.createdAt')}>{status?.created_at}</Descriptions.Item>
            <Descriptions.Item label={t('apiToken.expiresAt')}>
              {status?.expires_at ?? t('apiToken.neverExpire')}
            </Descriptions.Item>
          </Descriptions>
          <Alert type="info" showIcon message={t('apiToken.onePerPerson')} />
          <Popconfirm
            title={t('apiToken.deleteConfirm')}
            onConfirm={handleDelete}
          >
            <Button danger loading={loading}>{t('apiToken.delete')}</Button>
          </Popconfirm>
        </Space>
      )}

      {/* 无 token: 生成表单 */}
      {!plainToken && !hasToken && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Checkbox
              checked={neverExpire}
              onChange={(e) => setNeverExpire(e.target.checked)}
            >
              {t('apiToken.neverExpire')}
            </Checkbox>
          </div>
          {!neverExpire && (
            <DatePicker
              style={{ width: '100%' }}
              placeholder={t('apiToken.selectExpiry')}
              value={expiresAt}
              onChange={setExpiresAt}
              // 过期日期必须晚于今天, 禁用今天及之前 (避免选成一创建就已过期)
              disabledDate={(d) => d.isBefore(dayjs().endOf('day'))}
            />
          )}
          <Button type="primary" loading={loading} onClick={handleCreate}>
            {t('apiToken.generate')}
          </Button>
        </Space>
      )}
    </Modal>
  );
}
