import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { List, Modal, Select, Space, Tag, Typography, message } from 'antd';
import { listMembers } from '@/features/workspace/api';
import { useAppStore } from '@/store';
import {
  listShares,
  shareResource,
  unshareResource,
  type ShareItem,
  type ShareResType,
} from '@/api/sharing';

interface Props {
  wsId: string;
  resType: ShareResType;
  resId: string;
  open: boolean;
  onClose: () => void;
}

/**
 * 分享弹窗: 多选本 ws 成员分享 + 展示/移除已分享人。
 * 仅资源 creator 本人可见此入口 (调用方控制)。
 */
export default function ShareModal({ wsId, resType, resId, open, onClose }: Props) {
  const { t } = useTranslation(['sharing', 'common']);
  const [members, setMembers] = useState<{ label: string; value: string }[]>([]);
  const [shares, setShares] = useState<ShareItem[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const currentUser = useAppStore((s) => s.currentUser);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([listMembers(wsId), listShares(wsId, resType, resId)])
      .then(([ms, ss]) => {
        if (cancelled) return;
        // 过滤掉当前登录用户 — 不能分享给自己 (自己就是 creator)。
        setMembers(
          ms
            .filter((m) => m.user_id !== currentUser?.id)
            .map((m) => ({ label: m.display_name || m.user_id, value: m.user_id })),
        );
        setShares(ss);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, wsId, resType, resId, currentUser?.id]);

  const alreadyShared = new Set(shares.map((s) => s.target_username));

  const handleAdd = async () => {
    const toAdd = picked.filter((u) => !alreadyShared.has(u));
    if (!toAdd.length) {
      message.info(t('pickUnshared'));
      return;
    }
    setSaving(true);
    try {
      await shareResource(wsId, { res_type: resType, res_id: resId, target_usernames: toAdd });
      const ss = await listShares(wsId, resType, resId);
      setShares(ss);
      setPicked([]);
      message.success(t('shared'));
    } catch {
      message.error(t('shareFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (username: string) => {
    try {
      await unshareResource(wsId, resType, resId, username);
      setShares((prev) => prev.filter((s) => s.target_username !== username));
      message.success(t('unshared'));
    } catch {
      message.error(t('unshareFailed'));
    }
  };

  return (
    <Modal
      title={t('title')}
      open={open}
      onCancel={onClose}
      onOk={handleAdd}
      okText={t('okText')}
      cancelText={t('common:actions.close')}
      confirmLoading={saving}
      destroyOnClose
    >
      <Space direction="vertical" size={16} style={{ width: '100%', marginTop: 8 }}>
        <div>
          <Typography.Text strong>{t('pickMembers')}</Typography.Text>
          <Select
            mode="multiple"
            style={{ width: '100%', marginTop: 6 }}
            placeholder={loading ? t('loadingMembers') : t('placeholder')}
            loading={loading}
            disabled={loading}
            options={members}
            value={picked}
            onChange={setPicked}
            notFoundContent={loading ? t('loading') : t('noMembers')}
          />
        </div>
        <div>
          <Typography.Text strong>{t('sharedWith')}</Typography.Text>
          <List
            size="small"
            style={{ marginTop: 6 }}
            dataSource={shares}
            locale={{ emptyText: t('noShares') }}
            renderItem={(s) => (
              <List.Item
                actions={[
                  <a key="rm" onClick={() => handleRemove(s.target_username)}>
                    {t('remove')}
                  </a>,
                ]}
              >
                <Tag>{s.target_username}</Tag>
              </List.Item>
            )}
          />
        </div>
      </Space>
    </Modal>
  );
}
