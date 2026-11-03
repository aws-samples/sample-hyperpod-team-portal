import { Button, Form, Input, Radio, Select, Space, Tag, Tooltip, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import type { WorkspaceFsxMount, WorkspaceS3Mount } from '@/features/workspace/api';
import type { SharedPVCInfo } from '@/features/devinstance/api/client';
import type { ModelSourceType } from '../../api/types';

/** authedFsxMounts 项 = WorkspaceFsxMount + 关联 SharedPVCInfo 推出的 access/isPrimary。 */
export type AuthedFsxMount = WorkspaceFsxMount & {
  access: 'ro' | 'rw';
  isPrimary: boolean;
};

interface Props {
  modelSourceType: ModelSourceType;
  authedFsxMounts: AuthedFsxMount[];
  authedPvcs: SharedPVCInfo[] | null;
  fsxMounts: WorkspaceFsxMount[] | null;
  wsS3Mounts: WorkspaceS3Mount[] | null;
  onReload?: () => void;
  mountsLoading?: boolean;
}

/**
 * 模型来源 (原 step1): model_source_type (fsx/s3/huggingface) + model_name + 各源字段。
 * 受控展示组件: 授权 FSx 列表 (authedFsxMounts) + 加载态 (authedPvcs/fsxMounts) 由 index 下传。
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
  const { t } = useTranslation(['inference', 'common']);
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
          {/* HuggingFace Hub 暂去掉 (先不支持在线拉模型) */}
        </Radio.Group>
      </Form.Item>

      {/* 模型逻辑名 (CR.spec.modelName) 已去输入框: 自动用任务名 (name) 派生 —
          它只用于 SageMaker Model 资源命名, 不影响调用 (调用走 SGLang /opt/ml/model)。
          详见推理 modelName 调查记录。 */}

      {modelSourceType === 'fsx' && (
        <>
          {/* 外层 Form.Item 只管 label/tooltip/extra; 内层 noStyle Form.Item 带 name
              包住 Select 以保留 form 绑定 (裸 div 做直接子元素会吃掉注入的
              value/onChange → fsx_mount_id 不进 form)。 */}
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
                name="fsx_mount_id"
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
                options={authedFsxMounts.map((m) => ({
                  value: m.mount_id,
                  searchText: `${m.mount_id} ${m.mount_path}`,
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
                        {m.mount_id}
                      </Typography.Text>
                    </Space>
                  ),
                }))}
              />
              </Form.Item>
              {reloadBtn}
            </div>
          </Form.Item>
        </>
      )}

      {modelSourceType === 's3' && (
        <>
          {/* 内层 noStyle Form.Item 带 name 包住 Select 保留 form 绑定 (同上)。 */}
          <Form.Item
            label={t('create.model.s3Label')}
            required
            tooltip={t('create.model.s3Tooltip')}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Form.Item
                name="s3_mount_id"
                noStyle
                rules={[{ required: true, message: t('create.model.s3Required') }]}
              >
              <Select
                showSearch
                optionFilterProp="searchText"
                style={{ flex: 1 }}
                placeholder={
                  wsS3Mounts?.length
                    ? t('create.model.s3Placeholder')
                    : wsS3Mounts === null
                      ? t('create.model.s3Loading')
                      : t('create.model.s3PlaceholderEmpty')
                }
                notFoundContent={t('create.model.s3NotFound')}
                options={(wsS3Mounts ?? []).map((m) => ({
                  value: m.mount_id,
                  searchText: `${m.mount_id} ${m.bucket_name} ${m.mount_path}`,
                  label: (
                    <Space>
                      <Tag color="green">S3</Tag>
                      <span>{m.bucket_name}</span>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {m.region} · {m.mount_path}
                      </Typography.Text>
                    </Space>
                  ),
                }))}
              />
              </Form.Item>
              {reloadBtn}
            </div>
          </Form.Item>
          <Form.Item
            name="s3_model_location"
            label={t('create.model.s3PathLabel')}
            tooltip={t('create.model.s3PathTooltip')}
            rules={[{ required: true, message: t('create.model.s3PathRequired') }]}
            extra={t('create.model.s3PathExtra')}
          >
            <Input placeholder="models/qwen3-0-6b" />
          </Form.Item>
        </>
      )}
      {/* HuggingFace Hub 模型源暂去掉 (UI 不提供); 后端 huggingface 逻辑保留兼容 */}
    </>
  );
}
