import { useCallback, useEffect, useMemo, useState } from 'react';
import { AutoComplete, Button, Form, Space, Tooltip, Typography } from 'antd';
import {
  DownOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { listWorkspaceImages, type WorkspaceImage } from '@/api/registry';

const IMAGE_URI_PATTERN = /^[\w.\-/]+(:[\w.\-]+)$/;

interface Props {
  wsId: string;
  name: string;
  label: string;
  tooltip: string;
  placeholder: string;
}

/**
 * head/worker 镜像选择: AutoComplete 下拉镜像中心 (uses 含 training) + 可键入任意 URI。
 * 参数化以复用给 head_image / worker_image 两个字段 (参考训练/llm-d ImageSection)。
 */
export default function ImageField({ wsId, name, label, tooltip, placeholder }: Props) {
  const { t } = useTranslation(['rayjob', 'common']);
  const [images, setImages] = useState<WorkspaceImage[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    listWorkspaceImages(wsId)
      .then((list) => setImages(list.filter((img) => img.uses.includes('training'))))
      .catch(() => setImages([]))
      .finally(() => setLoading(false));
  }, [wsId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const options = useMemo(
    () =>
      images.map((img) => ({
        value: img.image_uri,
        label: (
          <Space size={6}>
            <Typography.Text>{img.display_name}</Typography.Text>
            <Typography.Text code style={{ fontSize: 12 }}>
              {img.image_uri}
            </Typography.Text>
          </Space>
        ),
      })),
    [images],
  );

  return (
    <Form.Item
      required
      label={
        <Space size={4}>
          {label}
          <Tooltip title={tooltip}>
            <QuestionCircleOutlined style={{ color: '#999' }} />
          </Tooltip>
        </Space>
      }
      extra={
        loading ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('create.image.loading')}
          </Typography.Text>
        ) : images.length === 0 ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            <Trans
              i18nKey="create.image.empty"
              ns="rayjob"
              components={{ registry: <Link to={`/workspaces/${wsId}/images`} /> }}
            />
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('create.image.hint')}
          </Typography.Text>
        )
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <Form.Item
          name={name}
          noStyle
          rules={[
            { required: true, message: t('create.image.required') },
            { pattern: IMAGE_URI_PATTERN, message: t('create.image.format') },
          ]}
        >
          <AutoComplete
            options={options}
            allowClear
            style={{ flex: 1 }}
            suffixIcon={<DownOutlined style={{ color: '#bfbfbf' }} />}
            placeholder={placeholder}
            filterOption={(input, option) => {
              const q = input.toLowerCase();
              if (images.some((i) => i.image_uri.toLowerCase() === q)) return true;
              return String(option?.value ?? '').toLowerCase().includes(q);
            }}
          />
        </Form.Item>
        <Tooltip title={t('common:actions.refresh')}>
          <Button
            type="text"
            icon={<ReloadOutlined style={{ color: '#999' }} />}
            loading={loading}
            onClick={reload}
          />
        </Tooltip>
      </div>
    </Form.Item>
  );
}
