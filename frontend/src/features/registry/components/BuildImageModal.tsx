import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Checkbox, Input, InputNumber, Modal, Select, Space, Typography, message } from 'antd';
import {
  submitImageBuild,
  type BuildComputeType,
  type ImageUse,
} from '@/api/registry';
import { ApiError } from '@/shared/api';
import { imageUseLabel } from '../mock';

const { Text } = Typography;

// 每档对应 AWS CodeBuild 的 compute 规格 (vCPU/内存/磁盘见下拉)。构建大镜像的瓶颈
// 是磁盘 (docker build 峰值 ≈ 最终镜像 × 2-3 倍, base+中间层+最终镜像同时在盘),
// 不是内存 —— 只有 2XLARGE(824GB 磁盘) 扛得住 40GB 大镜像。
// label 存 key, 渲染时再 t()。
const COMPUTE_OPTIONS = [
  { value: 'BUILD_GENERAL1_SMALL', labelKey: 'build.compute.small' },
  { value: 'BUILD_GENERAL1_MEDIUM', labelKey: 'build.compute.medium' },
  { value: 'BUILD_GENERAL1_LARGE', labelKey: 'build.compute.large' },
  { value: 'BUILD_GENERAL1_2XLARGE', labelKey: 'build.compute.xlarge2' },
] as const satisfies readonly { value: BuildComputeType; labelKey: string }[];

const USE_VALUES: ImageUse[] = ['dev', 'training', 'inference'];

interface Props {
  wsId: string;
  open: boolean;
  onClose: () => void;
  onSubmitted: () => void;
}

/**
 * 构建镜像弹窗: 填 Dockerfile + 目标 name:tag + 用途 + 规格 → 提交 CodeBuild 构建。
 * 只支持 Dockerfile 文本 (不上传本地文件); 构建成功后镜像自动注册进镜像中心。
 */
// 镜像名 = ECR repo 名原文 (期望 namespace/repo-name; 与后端 target_tag 的 name 段一致):
// 小写字母/数字开头, 段用单个 . _ - 分隔, / 分路径, 不允许大写/连续分隔符/首尾分隔符。
const IMAGE_NAME_RE = /^[a-z0-9]+(?:[._/-][a-z0-9]+)*$/;
// tag → docker tag 规范: 字母数字 + . _ - (可含大写)。
const IMAGE_TAG_RE = /^[a-zA-Z0-9._-]+$/;

export default function BuildImageModal({ wsId, open, onClose, onSubmitted }: Props) {
  const { t } = useTranslation(['registry', 'common']);
  const useOptions = USE_VALUES.map((v) => ({ value: v, label: imageUseLabel(v) }));
  const [dockerfile, setDockerfile] = useState(
    'FROM public.ecr.aws/sagemaker/sagemaker-distribution:latest-gpu\n',
  );
  const [imageName, setImageName] = useState('');
  const [imageTag, setImageTag] = useState('');
  const [uses, setUses] = useState<ImageUse[]>(['training']);
  const [compute, setCompute] = useState<BuildComputeType>('BUILD_GENERAL1_LARGE');
  const [timeoutMin, setTimeoutMin] = useState<number>(120);
  const [submitting, setSubmitting] = useState(false);

  // 行内校验错误 (输入非空且不合规时才提示, 空时不打扰)。
  const nameErr =
    imageName.trim() && !IMAGE_NAME_RE.test(imageName.trim())
      ? t('build.nameErr')
      : '';
  const tagErr =
    imageTag.trim() && !IMAGE_TAG_RE.test(imageTag.trim())
      ? t('build.tagErr')
      : '';

  const handleOk = async () => {
    const name = imageName.trim();
    const tag = imageTag.trim();
    if (!dockerfile.trim() || !name || !tag) {
      message.warning(t('build.missingFields'));
      return;
    }
    if (!IMAGE_NAME_RE.test(name)) {
      message.warning(t('build.nameInvalid'));
      return;
    }
    if (!IMAGE_TAG_RE.test(tag)) {
      message.warning(t('build.tagInvalid'));
      return;
    }
    if (!uses.length) {
      message.warning(t('build.pickUse'));
      return;
    }
    setSubmitting(true);
    try {
      await submitImageBuild(wsId, {
        dockerfile,
        target_tag: `${name}:${tag}`,
        uses,
        compute_type: compute,
        timeout_minutes: timeoutMin,
      });
      message.success(t('build.submitted'));
      onSubmitted();
      onClose();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('build.submitFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={t('build.title')}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText={t('build.okText')}
      cancelText={t('common:actions.cancel')}
      confirmLoading={submitting}
      width={680}
      destroyOnClose
    >
      <Space direction="vertical" size={16} style={{ width: '100%', marginTop: 8 }}>
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <Text strong>{t('build.imageName')}</Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
              {t('build.imageNameHint')}
            </Text>
            <Input
              status={nameErr ? 'error' : undefined}
              style={{ marginTop: 6 }}
              placeholder={t('build.imageNamePlaceholder')}
              value={imageName}
              onChange={(e) => setImageName(e.target.value)}
            />
            <Text
              type={nameErr ? 'danger' : 'secondary'}
              style={{ fontSize: 12, display: 'block', marginTop: 4 }}
            >
              {nameErr || t('build.imageNameRule')}
            </Text>
          </div>
          <div style={{ width: 200 }}>
            <Text strong>tag</Text>
            <Input
              status={tagErr ? 'error' : undefined}
              style={{ marginTop: 6 }}
              placeholder={t('build.tagPlaceholder')}
              value={imageTag}
              onChange={(e) => setImageTag(e.target.value)}
            />
            <Text
              type={tagErr ? 'danger' : 'secondary'}
              style={{ fontSize: 12, display: 'block', marginTop: 4 }}
            >
              {tagErr || t('build.tagRule')}
            </Text>
          </div>
        </div>
        <div>
          <Text strong>Dockerfile</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            {t('build.dockerfileHint')}
          </Text>
          <Input.TextArea
            style={{ marginTop: 6, fontFamily: 'monospace' }}
            rows={10}
            value={dockerfile}
            onChange={(e) => setDockerfile(e.target.value)}
          />
        </div>
        <div>
          <Text strong>{t('build.uses')}</Text>
          <div style={{ marginTop: 6 }}>
            <Checkbox.Group
              options={useOptions}
              value={uses}
              onChange={(v) => setUses(v as ImageUse[])}
            />
          </div>
        </div>
        <div>
          <Text strong>{t('build.spec')}</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            {t('build.specHint')}
          </Text>
          <Select
            style={{ width: '100%', marginTop: 6 }}
            value={compute}
            onChange={setCompute}
            options={COMPUTE_OPTIONS.map((o) => ({ value: o.value, label: t(o.labelKey) }))}
          />
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
            {t('build.specHelp')}
          </Text>
        </div>
        <div>
          <Text strong>{t('build.timeout')}</Text>
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            {t('build.timeoutHint')}
          </Text>
          <div style={{ marginTop: 6 }}>
            <InputNumber
              min={5}
              max={480}
              step={30}
              value={timeoutMin}
              onChange={(v) => setTimeoutMin(v ?? 120)}
              addonAfter={t('build.minutes')}
              style={{ width: 180 }}
            />
          </div>
        </div>
      </Space>
    </Modal>
  );
}
