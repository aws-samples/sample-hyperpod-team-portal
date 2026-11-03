import { useState } from 'react';
import { App, Button, Input, Modal, Space, Spin, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { Trans, useTranslation } from 'react-i18next';
import { addAuthorizedKey } from '../api/client';
import type { AccessInfo } from '../api/types';

interface Props {
  open: boolean;
  access: AccessInfo | null;
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
}

const codeBlockStyle: React.CSSProperties = {
  background: '#f5f5f5',
  border: '1px solid #e8e8e8',
  borderRadius: 4,
  padding: '8px 12px',
  margin: 0,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: 12,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
  color: '#262626',
};

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: '#262626',
};

const helpTextStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#8c8c8c',
  display: 'block',
  marginTop: 4,
};

/**
 * 连接开发机弹窗 · directSSH (原生 SSH + 固定 DNS 名):
 *   ① 配置公钥 (首次必做, 用户在 code editor 里贴)
 *   ② 终端连接 (ssh 一行, 直连内网固定 DNS 的 sshd:22222)
 *   ③ VSCode Remote-SSH (~/.ssh/config 片段, 固定 DNS 无 ProxyCommand)
 *
 * loading 期间显示 Spin (避免数据返回前闪烁"实例尚未就绪")。
 */
export default function ConnectModal({
  open,
  access,
  loading,
  onClose,
  onRefresh,
}: Props) {
  const { t } = useTranslation(['devinstance', 'common']);
  const { message } = App.useApp();
  const sshCommand = access?.ssh_command || null;
  const sshSnippet = access?.ssh_config_snippet || null;
  const hostname = access?.ssh_hostname || null;
  const sshUser = access?.ssh_user || 'sagemaker-user';
  const ready = Boolean(sshCommand || hostname);
  const instanceId = access?.id || null;

  // 自动写入公钥: 用户粘公钥 → 平台代跑 authorized_keys 写入 (免手动进 code editor 终端)。
  const [pubkey, setPubkey] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleAutoWrite = async () => {
    const key = pubkey.trim();
    if (!key) {
      message.warning(t('connect.key.empty'));
      return;
    }
    if (!instanceId) return;
    setSubmitting(true);
    try {
      const res = await addAuthorizedKey(instanceId, key);
      message.success(res.message || t('connect.key.written'));
      setPubkey('');
    } catch (e) {
      message.error(e instanceof Error ? e.message : t('connect.key.writeFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  // 公钥追加命令 (在开发机 code editor 终端里跑): 把用户本地公钥内容贴进 authorized_keys。
  const authKeysCmd =
    'mkdir -p ~/.ssh && chmod 700 ~/.ssh && \\\n' +
    t('connect.key.echoLine') + '\n' +
    'chmod 600 ~/.ssh/authorized_keys';

  return (
    <Modal
      title={t('connect.title')}
      open={open}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnClose
    >
      {loading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin tip={t('connect.preparing')} size="large">
            <div style={{ minHeight: 60 }} />
          </Spin>
        </div>
      )}

      {!loading && !ready && (
        <Typography.Text type="secondary">
          {t('connect.notReady')}
        </Typography.Text>
      )}

      {!loading && ready && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <span style={sectionLabelStyle}>{t('connect.ssh.title')}</span>
            <Typography.Text style={helpTextStyle}>
              {t('connect.ssh.desc')}
            </Typography.Text>
          </div>

          {/* ① 配置公钥 (首次必做) · 粘公钥 → 平台代写入 */}
          <div>
            <span style={sectionLabelStyle}>{t('connect.key.title')}</span>
            <Typography.Text style={helpTextStyle}>
              <Trans
                i18nKey="connect.key.desc"
                ns="devinstance"
                components={{ code: <Typography.Text code /> }}
              />
            </Typography.Text>
            <Input.TextArea
              value={pubkey}
              onChange={(e) => setPubkey(e.target.value)}
              placeholder="ssh-ed25519 AAAA... your-comment"
              autoSize={{ minRows: 2, maxRows: 4 }}
              style={{ marginTop: 8, fontFamily: codeBlockStyle.fontFamily, fontSize: 12 }}
            />
            <div style={{ marginTop: 8, textAlign: 'right' }}>
              <Button
                type="primary"
                size="small"
                loading={submitting}
                onClick={handleAutoWrite}
              >
                {t('connect.key.autoWrite')}
              </Button>
            </div>
            <Typography.Text style={helpTextStyle}>
              {t('connect.key.manualHint')}
            </Typography.Text>
            <Typography.Paragraph
              copyable={{
                text: authKeysCmd,
                tooltips: [t('common:actions.copy'), t('common:messages.copied')],
                onCopy: () => message.success(t('connect.key.copied')),
              }}
              style={{ ...codeBlockStyle, marginTop: 8 }}
            >
              {authKeysCmd}
            </Typography.Paragraph>
          </div>

          {/* ② 终端连接 · ssh 一行 */}
          {sshCommand && (
            <div>
              <span style={sectionLabelStyle}>{t('connect.terminal.title')}</span>
              <Typography.Text style={helpTextStyle}>
                {t('connect.terminal.desc', { user: sshUser })}
              </Typography.Text>
              <Typography.Paragraph
                copyable={{
                  text: sshCommand,
                  tooltips: [t('common:actions.copy'), t('common:messages.copied')],
                  onCopy: () => message.success(t('connect.terminal.copied')),
                }}
                style={{ ...codeBlockStyle, marginTop: 8 }}
              >
                {sshCommand}
              </Typography.Paragraph>
            </div>
          )}

          {/* ③ VSCode Remote-SSH · config 片段 */}
          {sshSnippet && (
            <div>
              <span style={sectionLabelStyle}>{t('connect.vscode.title')}</span>
              <Typography.Text style={helpTextStyle}>
                {t('connect.vscode.desc')}
              </Typography.Text>
              <Typography.Paragraph
                copyable={{
                  text: sshSnippet,
                  tooltips: [t('common:actions.copy'), t('common:messages.copied')],
                  onCopy: () => message.success(t('connect.vscode.copied')),
                }}
                style={{ ...codeBlockStyle, marginTop: 8 }}
              >
                {sshSnippet}
              </Typography.Paragraph>
            </div>
          )}

          {/* 刷新 */}
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
            <a onClick={onRefresh}>
              <ReloadOutlined /> {t('common:actions.refresh')}
            </a>{' '}
            {t('connect.refreshHint')}
          </Typography.Paragraph>
        </Space>
      )}
    </Modal>
  );
}
