import { Form, Tooltip } from 'antd';
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
 * 启动配置 (照推理 CommandSection): 一个启动脚本框 (launch_script), 后端渲
 * worker.command=["/bin/sh","-c"], args=[脚本整段]。脚本用 exec 接管主进程;
 * 必须含 --model-path (FSx 写 /fsx/<模型目录>) + --tp-size/--ep-size。
 */
export default function CommandSection() {
  const { t } = useTranslation('dynamo');
  return (
    <>
      <SectionHeading
        title={t('create.launch.heading')}
        help={
          <span>
            <Trans
              i18nKey="create.launch.help"
              ns="dynamo"
              components={{
                br: <br />,
                modelDir: <>&lt;{t('create.launch.script.modelDir')}&gt;</>,
              }}
            />
          </span>
        }
      />
      <Form.Item
        name="launch_script"
        rules={[{ required: true, message: t('create.launch.scriptRequired') }]}
        extra={t('create.launch.scriptExtra')}
      >
        <ScriptEditor height={180} language="shell" langLabel="Shell" />
      </Form.Item>
    </>
  );
}
