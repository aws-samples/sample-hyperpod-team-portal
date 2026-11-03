import { Form, Input, Radio, Select, Space, Tag, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import type { WorkspaceFsxMount, WorkspaceS3Mount } from '@/features/workspace/api';
import type { SharedPVCInfo } from '@/features/devinstance/api/client';
import type { DynamoModelSourceType } from '../../api/types';

export type AuthedFsxMount = WorkspaceFsxMount & {
  access: 'ro' | 'rw';
  isPrimary: boolean;
};

interface Props {
  modelSourceType: DynamoModelSourceType;
  authedFsxMounts: AuthedFsxMount[];
  authedPvcs: SharedPVCInfo[] | null;
  fsxMounts: WorkspaceFsxMount[] | null;
  wsS3Mounts: WorkspaceS3Mount[] | null;
}

/**
 * 模型来源 (照推理 ModelSourceSection): Radio(fsx/s3) + 授权挂载源下拉。
 * FSx 选授权挂载源 → 提交其 pvc_name (后端反查 mount_path); 模型路径在启动脚本 --model-path 写。
 * S3 选挂载源 (bucket/region 自动带出) + 模型相对路径。
 */
export default function ModelSourceSection({
  modelSourceType,
  authedFsxMounts,
  authedPvcs,
  fsxMounts,
  wsS3Mounts,
}: Props) {
  const { t } = useTranslation(['dynamo', 'common']);
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
        <Form.Item
          name="fsx_pvc_name"
          label={t('create.model.fsxLabel')}
          tooltip={t('create.model.fsxTooltip')}
          rules={[{ required: true, message: t('create.model.fsxRequired') }]}
          extra={
            authedPvcs === null || fsxMounts === null
              ? t('create.model.fsxLoading')
              : authedFsxMounts.length === 0
                ? t('create.model.fsxNone')
                : t('create.model.fsxHint')
          }
        >
          <Select
            showSearch
            optionFilterProp="searchText"
            placeholder={
              authedFsxMounts.length
                ? t('create.model.fsxPlaceholder')
                : t('create.model.fsxPlaceholderEmpty')
            }
            notFoundContent={t('create.model.fsxNotFound')}
            options={authedFsxMounts.map((m) => {
              // 提交 pvc_name: rw 优先 (与后端授权反查一致)
              const pvc = m.pvc_name_rw || m.pvc_name_ro || m.pvc_name || '';
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
      )}

      {modelSourceType === 's3' && (
        <>
          <Form.Item
            name="s3_mount_id"
            label={t('create.model.s3Label')}
            tooltip={t('create.model.s3Tooltip')}
            rules={[{ required: true, message: t('create.model.s3Required') }]}
          >
            <Select
              showSearch
              optionFilterProp="searchText"
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
          <Form.Item
            name="s3_model_location"
            label={t('create.model.s3PathLabel')}
            tooltip={t('create.model.s3PathTooltip')}
            rules={[{ required: true, message: t('create.model.s3PathRequired') }]}
            extra={t('create.model.s3PathExtra')}
          >
            <Input placeholder="models/deepseek-v3" />
          </Form.Item>
        </>
      )}
    </>
  );
}
