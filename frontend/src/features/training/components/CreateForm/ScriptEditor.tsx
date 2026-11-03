import { useState } from 'react';
import { Modal, Tooltip, Typography, message } from 'antd';
import {
  CopyOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
} from '@ant-design/icons';
import Editor from '@monaco-editor/react';
import { useTranslation } from 'react-i18next';

interface Props {
  /** 受控值 (Form.Item 注入) */
  value?: string;
  /** 受控 onChange (Form.Item 注入) */
  onChange?: (v: string) => void;
  language?: string;
  height?: number | string;
  readOnly?: boolean;
  /** 编辑器左上语言标签文字 (默认 Shell) */
  langLabel?: string;
}

/**
 * 带顶部标签栏的脚本编辑器 (照阿里云启动命令格式)。
 * 标签栏: 左 语言标签 (Shell) · 右 字符数 + 复制 + 全屏。
 * 受控组件 (绑 Form.Item value/onChange); 全屏走 Modal 放大编辑, 共用同一 value。
 */
export default function ScriptEditor({
  value = '',
  onChange,
  language = 'shell',
  height = 380,
  readOnly = false,
  langLabel = 'Shell',
}: Props) {
  const { t } = useTranslation('common');
  const [fullscreen, setFullscreen] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      message.success(t('messages.copied'));
    } catch {
      message.error(t('messages.copyFailed'));
    }
  };

  // 顶部标签栏 (左 lang 标签 / 右 字符数 + 工具按钮)
  const bar = (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '4px 12px',
        background: '#fafafa',
        borderBottom: '1px solid #d9d9d9',
        fontSize: 12,
        color: 'rgba(0,0,0,0.45)',
      }}
    >
      <span>{langLabel}</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span>{t('scriptEditor.typed', { count: value.length })}</span>
        <Tooltip title={t('actions.copy')}>
          <CopyOutlined style={{ cursor: 'pointer' }} onClick={copy} />
        </Tooltip>
        <Tooltip title={
            fullscreen
              ? t('scriptEditor.exitFullscreen')
              : t('scriptEditor.fullscreen')
          }>
          {fullscreen ? (
            <FullscreenExitOutlined
              style={{ cursor: 'pointer' }}
              onClick={() => setFullscreen(false)}
            />
          ) : (
            <FullscreenOutlined
              style={{ cursor: 'pointer' }}
              onClick={() => setFullscreen(true)}
            />
          )}
        </Tooltip>
      </span>
    </div>
  );

  const editor = (h: number | string) => (
    <Editor
      height={h}
      language={language}
      theme="light"
      value={value}
      onChange={(v) => onChange?.(v ?? '')}
      options={{
        readOnly,
        minimap: { enabled: false },
        fontSize: 12,
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
      }}
    />
  );

  return (
    <>
      <div style={{ border: '1px solid #d9d9d9', borderRadius: 6, overflow: 'hidden' }}>
        {bar}
        {editor(height)}
      </div>
      <Modal
        open={fullscreen}
        onCancel={() => setFullscreen(false)}
        footer={null}
        width="90vw"
        style={{ top: 24 }}
        title={
          <Typography.Text>
            {t('scriptEditor.typedTitle', {
              lang: langLabel,
              count: value.length,
            })}
          </Typography.Text>
        }
        destroyOnClose
      >
        {editor('75vh')}
      </Modal>
    </>
  );
}
