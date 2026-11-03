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
 * 启动配置 (照 dynamo CommandSection): 一个 launch_script 框, 后端渲
 * sglang command=["/bin/sh","-c"], args=[脚本整段]。leader/worker 共用同一脚本。
 * --model-path 写 /model/<模型目录> (模型源挂到 /model); 多机组网靠 LWS 注入的
 * $LWS_LEADER_ADDRESS/$LWS_GROUP_SIZE/$LWS_WORKER_INDEX (shell 形式, 别写 $(...))。
 */
export default function CommandSection() {
  const { t } = useTranslation('llmd');
  return (
    <>
      <SectionHeading
        title={t('create.launch.heading')}
        help={
          <span>
            <Trans
              i18nKey="create.launch.help"
              ns="llmd"
              components={{
                br: <br />,
                relPath: <>&lt;{t('create.launch.relPath')}&gt;</>,
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
        <ScriptEditor height={200} language="shell" langLabel="Shell" />
      </Form.Item>
    </>
  );
}
