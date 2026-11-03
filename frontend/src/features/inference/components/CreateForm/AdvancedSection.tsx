import type { ReactNode } from 'react';
import { Button, Typography } from 'antd';
import { Trans, useTranslation } from 'react-i18next';
import { ReloadOutlined } from '@ant-design/icons';
import ScriptEditor from '@/features/training/components/CreateForm/ScriptEditor';

const { Text } = Typography;

interface Props {
  wsId: string;
  previewYaml: string;
  // 当前 name (用于 S3 存档路径展示), 由 index 经 Form.useWatch 下传
  currentName: string;
  // 点按钮触发后端 preview 渲染 (单页后不再绑 step3)
  onPreview: () => void;
}

function SectionHeading({ title }: { title: ReactNode }) {
  return <div style={{ fontWeight: 500, marginBottom: 12 }}>{title}</div>;
}

/**
 * 预览 (照训练 PreviewSection, 无卡片 + 白底 ScriptEditor): 后端真渲染 YAML。
 * metrics 开关已移入「启动配置」(CommandSection)。预览点按钮触发。
 */
export default function AdvancedSection({ wsId, previewYaml, currentName, onPreview }: Props) {
  const { t } = useTranslation('inference');
  return (
    <>
      <SectionHeading title={t('create.preview.heading')} />
      <Button
        icon={<ReloadOutlined />}
        onClick={onPreview}
        style={{ marginBottom: 12 }}
      >
        {t('create.preview.refresh')}
      </Button>
      <ScriptEditor
        readOnly
        language="yaml"
        langLabel="YAML"
        height={420}
        value={previewYaml || t('create.preview.placeholder')}
      />
      <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        <Trans
          i18nKey="create.preview.archive"
          ns="inference"
          components={{
            path: (
              <code>
                s3://&lt;workspace-bucket&gt;/{wsId}/&lt;user&gt;/
                {currentName || '<task>'}/test-{currentName || '<task>'}.yaml
              </code>
            ),
          }}
        />
      </Text>
    </>
  );
}
