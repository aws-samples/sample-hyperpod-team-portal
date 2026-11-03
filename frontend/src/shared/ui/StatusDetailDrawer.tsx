import { useEffect, useState } from 'react';
import { App, Button, Drawer } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';

/**
 * status_detail 只读侧边抽屉 (debug 用) —— 与 KueueDetailDrawer 一致, 从右侧划出。
 *
 * - 打开时 (open 变 true 且 detailId 有值) 调 fetcher 查接口。
 * - 内容 JSON 缩进格式化, 只读 pre 可选中复制, 顶部右上角有复制按钮。
 *
 * 与 StatusDetailModal 同 props, 详情页用抽屉 (和 Kueue 详情一致), 列表页仍用弹窗。
 */
export default function StatusDetailDrawer({
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
    <Drawer
      open={open}
      title={title ?? t('statusDetail.title')}
      width={760}
      onClose={onClose}
      extra={
        <Button size="small" icon={<CopyOutlined />} onClick={copy} disabled={!text}>
          {t('actions.copy')}
        </Button>
      }
    >
      <pre
        style={{
          margin: 0,
          background: '#f6f8fa',
          padding: 12,
          borderRadius: 6,
          fontSize: 12,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {loading ? t('messages.loading') : text || t('messages.none')}
      </pre>
    </Drawer>
  );
}
