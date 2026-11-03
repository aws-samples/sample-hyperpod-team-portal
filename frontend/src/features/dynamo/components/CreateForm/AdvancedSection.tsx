import type { ReactNode } from 'react';
import { Button } from 'antd';
import { useTranslation } from 'react-i18next';
import { ReloadOutlined } from '@ant-design/icons';
import ScriptEditor from '@/features/training/components/CreateForm/ScriptEditor';

interface Props {
  previewYaml: string;
  onPreview: () => void;
}

function SectionHeading({ title }: { title: ReactNode }) {
  return <div style={{ fontWeight: 500, marginBottom: 12 }}>{title}</div>;
}

/**
 * 预览 (照推理 AdvancedSection): 后端真渲染 DynamoGraphDeployment YAML (预览即真相)。
 */
export default function AdvancedSection({ previewYaml, onPreview }: Props) {
  const { t } = useTranslation('dynamo');
  return (
    <>
      <SectionHeading title={t('create.preview.heading')} />
      <Button icon={<ReloadOutlined />} onClick={onPreview} style={{ marginBottom: 12 }}>
        {t('create.preview.refresh')}
      </Button>
      <ScriptEditor
        readOnly
        language="yaml"
        langLabel="YAML"
        height={420}
        value={previewYaml || t('create.preview.placeholder')}
      />
    </>
  );
}
