import { Form, Switch, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { Trans, useTranslation } from 'react-i18next';
import ScriptEditor from '@/features/training/components/CreateForm/ScriptEditor';

import type { ReactNode } from 'react';

function SectionHeading({ title, help }: { title: ReactNode; help: ReactNode }) {
  return (
    <div style={{ fontWeight: 500, marginBottom: 12 }}>
      {title}
      <Tooltip title={help}>
        <QuestionCircleOutlined style={{ color: '#999', marginLeft: 6, cursor: 'help' }} />
      </Tooltip>
    </div>
  );
}

/**
 * 启动配置 (合并单脚本, 照训练 LaunchSection):
 * 一个启动脚本框 (launch_script), 后端渲 command=["/bin/sh","-c"], args=[脚本整段]。
 * 脚本用 exec 接管主进程; 必须含 --model-path <模型绝对路径>。+ metrics 开关。
 */
export default function CommandSection() {
  const { t } = useTranslation('inference');
  return (
    <>
      <SectionHeading
        title={t('create.launch.heading')}
        help={
          <span>
            <Trans
              i18nKey="create.launch.help"
              ns="inference"
              components={{ br: <br /> }}
            />
          </span>
        }
      />
      <Form.Item
        name="launch_script"
        rules={[{ required: true, message: t('create.launch.scriptRequired') }]}
        extra={t('create.launch.scriptExtra')}
      >
        <ScriptEditor height={160} language="shell" langLabel="Shell" />
      </Form.Item>

      <div style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span>{t('create.launch.metricsLabel')}</span>
          <Form.Item name="metrics_enabled" valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
        </div>
        <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
          {t('create.launch.metricsHint')}
        </Typography.Text>
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span>{t('create.launch.publicLabel')}</span>
          <Form.Item name="public_endpoint" valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
        </div>
        <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
          {t('create.launch.publicHint')}
        </Typography.Text>
      </div>
    </>
  );
}
