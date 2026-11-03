import type { ReactNode } from 'react';
import { Button, Form } from 'antd';
import { useTranslation } from 'react-i18next';
import { ReloadOutlined } from '@ant-design/icons';
import ScriptEditor from './ScriptEditor';

function SectionHeading({ title }: { title: ReactNode }) {
  return <div style={{ fontWeight: 500, marginBottom: 12 }}>{title}</div>;
}

export interface PreviewSectionProps {
  previewYaml: string;
  previewLoading: boolean;
  onRefreshPreview: () => void;
  // runPolicy 是 PyTorchJob 专有嵌套字段; RayJob 无此概念 → 传 false 隐藏该编辑块。
  showRunPolicy?: boolean;
}

/**
 * 注: rayjob 的创建表单也复用本组件 (文案在 training ns 的 create.preview.*)。
 *
 * 预览 (原 step4+5 合并): 后端渲染真·最终 CR (只读) + runPolicy 可编辑。
 * 两个代码块统一用 ScriptEditor (带 YAML 标签栏 + 字符数 + 复制 + 全屏, 同脚本内容)。
 * 单页无翻页 → "刷新预览" 按钮主动触发后端渲染; previewYaml/loading 由 index 传; runpolicy_yaml 绑 form。
 */
export default function PreviewSection({
  previewYaml,
  previewLoading,
  onRefreshPreview,
  showRunPolicy = true,
}: PreviewSectionProps) {
  const { t } = useTranslation('training');
  return (
    <>
      <SectionHeading title={t('create.preview.heading')} />
      <Button
        icon={<ReloadOutlined />}
        onClick={onRefreshPreview}
        loading={previewLoading}
        style={{ marginBottom: 12 }}
      >
        {t('create.preview.refresh')}
      </Button>
      <ScriptEditor
        readOnly
        language="yaml"
        langLabel="YAML"
        height={360}
        value={
          previewLoading
            ? t('create.preview.rendering')
            : previewYaml || t('create.preview.placeholder')
        }
      />
      {showRunPolicy && (
        <Form.Item
          name="runpolicy_yaml"
          label={
            <span>
              {t('create.preview.runPolicyLabel')}{' '}
              <a
                href="https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-eks-operator-usage.html"
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 12, fontWeight: 'normal' }}
              >
                {t('create.preview.refDocs')}
              </a>
            </span>
          }
          tooltip={t('create.preview.runPolicyTooltip')}
          style={{ marginTop: 16, marginBottom: 0 }}
        >
          <ScriptEditor language="yaml" langLabel="YAML" height={200} />
        </Form.Item>
      )}
    </>
  );
}
