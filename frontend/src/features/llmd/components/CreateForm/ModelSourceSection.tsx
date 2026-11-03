import { Button, Form, Input, Radio, Select, Space, Tag, Tooltip, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { WorkspaceFsxMount, WorkspaceS3Mount } from '@/features/workspace/api';
import type { SharedPVCInfo } from '@/features/devinstance/api/client';
import type { LlmdModelSourceType } from '../../api/types';

export type AuthedFsxMount = WorkspaceFsxMount & {
  access: 'ro' | 'rw';
  isPrimary: boolean;
};

interface Props {
  modelSourceType: LlmdModelSourceType;
  authedFsxMounts: AuthedFsxMount[];
  authedPvcs: SharedPVCInfo[] | null;
  fsxMounts: WorkspaceFsxMount[] | null;
  wsS3Mounts: WorkspaceS3Mount[] | null;
  onReload?: () => void;
  mountsLoading?: boolean;
}

/**
 * 模型来源 (照 dynamo ModelSourceSection): Radio(fsx/s3) + 挂载源下拉, 都走 PVC (sglang 无感)。
 * FSx 选授权挂载源 → 提交其 pvc_name (后端反查 mount_path); 模型绝对路径 (含 /fsx) 直接填。
 * S3 选 ws 已挂 S3 挂载 (mount_id, bucket/挂载点自动带出) + 模型相对路径 (后端拼挂载点)。
 */
export default function ModelSourceSection({
  modelSourceType,
  authedFsxMounts,
  authedPvcs,
  fsxMounts,
  wsS3Mounts,
  onReload,
  mountsLoading,
}: Props) {
  const { t } = useTranslation(['llmd', 'common']);
  // FSx/S3 单选框右侧共用的刷新按钮; 未传 onReload 则不渲染。
  const reloadBtn = onReload ? (
    <Tooltip title={t('common:actions.refresh')}>
      <Button
        type="text"
        icon={<ReloadOutlined style={{ color: '#999' }} />}
        loading={mountsLoading}
        onClick={onReload}
      />
    </Tooltip>
  ) : null;
  return (
    <>
      <Form.Item
        name="model_source_type"
        label={t('create.model.sourceLabel')}
        rules={[{ required: true }]}
      >
        <Radio.Group optionType="button" buttonStyle="solid">
          <Radio.Button value="fsx">{t('create.model.fsxOption')}</Radio.Button>
          <Radio.Button value="s3">S3</Radio.Button>
        </Radio.Group>
      </Form.Item>

      {modelSourceType === 'fsx' && (
        <>
          {/* 外层 Form.Item 只管 label/tooltip/extra; 内层 noStyle Form.Item 带 name
              包住 Select 保留 form 绑定 (裸 div 做直接子元素会吃掉 value/onChange
              → model_pvc 不进 form)。 */}
          <Form.Item
            label={t('create.model.fsxLabel')}
            required
            tooltip={t('create.model.fsxTooltip')}
            extra={
              authedPvcs === null || fsxMounts === null
                ? t('create.model.fsxLoading')
                : authedFsxMounts.length === 0
                  ? t('create.model.fsxNone')
                  : t('create.model.fsxHint')
            }
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Form.Item
                name="model_pvc"
                noStyle
                rules={[{ required: true, message: t('create.model.fsxRequired') }]}
              >
              <Select
                showSearch
                optionFilterProp="searchText"
                style={{ flex: 1 }}
                placeholder={
                  authedFsxMounts.length
                    ? t('create.model.fsxPlaceholder')
                    : t('create.model.fsxPlaceholderEmpty')
                }
                notFoundContent={t('create.model.fsxNotFound')}
                options={authedFsxMounts.map((m) => {
                  // 按自己的 access 选: ws 挂载对每块盘都带 rw 名, 只读用户传它会 403
                  const pvc =
                    (m.access === 'rw' ? m.pvc_name_rw : m.pvc_name_ro) ||
                    m.pvc_name ||
                    '';
                  return {
                    value: pvc,
                    searchText: `${pvc} ${m.mount_path}`,
                    label: (
                      <Space>
                        <Tag color="blue">FSx</Tag>
                        {m.isPrimary && <Tag color="purple">{t('common:storagePicker.primary')}</Tag>}
                        <Tag color={m.access === 'rw' ? 'gold' : 'default'}>
                          {m.access === 'rw'
                            ? t('common:storagePicker.readWrite')
                            : t('common:storagePicker.readOnly')}
                        </Tag>
                        <span>{m.mount_path}</span>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {pvc}
                        </Typography.Text>
                      </Space>
                    ),
                  };
                })}
              />
              </Form.Item>
              {reloadBtn}
            </div>
          </Form.Item>

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('create.model.modelDiskHint')}
          </Typography.Text>
        </>
      )}

      {modelSourceType === 's3' && (
        <>
          {/* 内层 noStyle Form.Item 带 name 包住 Select 保留 form 绑定 (同上)。 */}
          <Form.Item
            label="S3 Bucket"
            required
            tooltip={t('create.model.s3Tooltip')}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Form.Item
                name="s3_bucket"
                noStyle
                rules={[{ required: true, message: t('create.model.s3Required') }]}
              >
              <Select
                showSearch
                style={{ flex: 1 }}
                placeholder={
                  wsS3Mounts?.length
                    ? t('create.model.s3Placeholder')
                    : wsS3Mounts === null
                      ? t('create.model.s3Loading')
                      : t('create.model.s3PlaceholderEmpty')
                }
                notFoundContent={t('create.model.s3NotFound')}
                options={Array.from(
                  new Set((wsS3Mounts ?? []).map((m) => m.bucket_name).filter(Boolean)),
                ).map((bucket) => ({
                  value: bucket,
                  label: (
                    <Space>
                      <Tag color="green">S3</Tag>
                      <span>{bucket}</span>
                    </Space>
                  ),
                }))}
              />
              </Form.Item>
              {reloadBtn}
            </div>
          </Form.Item>
          <Form.Item
            name="s3_prefix"
            label={t('create.model.s3PrefixLabel')}
            tooltip={t('create.model.s3PrefixTooltip')}
            rules={[{ required: true, message: t('create.model.s3PrefixRequired') }]}
            extra={t('create.model.s3PrefixExtra')}
          >
            <Input placeholder="models/qwen2.5-0.5b" />
          </Form.Item>
        </>
      )}
    </>
  );
}
