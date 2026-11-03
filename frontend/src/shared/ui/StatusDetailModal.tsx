import { useEffect, useState } from 'react';
import { App, Button, Modal, Space } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

/**
 * status_detail 只读弹窗 (debug 用)。
 * - 打开时 (open 变 true 且 detailId 有值) 调 fetcher 查接口, 不进 list。
 * - 内容 JSON 缩进格式化, 只读 pre 可选中复制, 有复制按钮 + 关闭按钮。
 */
export default function StatusDetailModal({
  open,
  title,
  detailId,
  fetcher,
  onClose,
}: {
  open: boolean;
  title?: string;
  detailId: string | null;
  fetcher: (id: string) => Promise<{ status_detail: unknown }>;
  onClose: () => void;
}) {
  const { t } = useTranslation('common');
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState('');

  useEffect(() => {
    if (!open || !detailId) return;
    setLoading(true);
    setText('');
    fetcher(detailId)
      .then((res) => {
        setText(JSON.stringify(res.status_detail ?? null, null, 2));
      })
      .catch((e) => message.error(t('statusDetail.loadFailed', { error: String(e) })))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, detailId]);

  const copy = () => {
    navigator.clipboard.writeText(text).then(
      () => message.success(t('messages.copied')),
      () => message.error(t('messages.copyFailed')),
    );
  };

  return (
    <Modal
      open={open}
      title={title ?? t('statusDetail.title')}
      onCancel={onClose}
      width={720}
      footer={[
        <Button key="copy" icon={<CopyOutlined />} onClick={copy} disabled={!text}>
          {t('actions.copy')}
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>
          {t('actions.close')}
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <pre
          style={{
            maxHeight: 460,
            overflow: 'auto',
            background: '#f6f8fa',
            padding: 12,
            borderRadius: 6,
            margin: 0,
            fontSize: 12,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {loading ? t('messages.loading') : text || t('messages.none')}
        </pre>
      </Space>
    </Modal>
  );
}
