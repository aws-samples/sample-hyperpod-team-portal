import { useEffect, useMemo, useState } from 'react';
import { AutoComplete, Form, Space, Tooltip, Typography } from 'antd';
import { QuestionCircleOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { listWorkspaceImages, type WorkspaceImage } from '@/api/registry';

const IMAGE_URI_PATTERN = /^[\w.\-/]+(:[\w.\-]+)$/;

interface Props {
  wsId: string;
}

/**
 * Dynamo 镜像选择 · 照推理 ImageSection: AutoComplete 下拉镜像中心 (uses 含 inference)
 * + 可键入任意 URI。绑 form 的 image 字段。默认值给 dynamo sglang-runtime EFA 镜像。
 */
export default function ImageSection({ wsId }: Props) {
  const { t } = useTranslation('dynamo');
  const [images, setImages] = useState<WorkspaceImage[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!wsId) return;
    let cancelled = false;
    setLoading(true);
    listWorkspaceImages(wsId)
      .then((list) => {
        if (!cancelled) setImages(list.filter((img) => img.uses.includes('inference')));
      })
      .catch(() => {
        if (!cancelled) setImages([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [wsId]);

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
      name="image"
      label={
        <Space size={4}>
          {t('create.image.label')}
          <Tooltip title={t('create.image.help')}>
            <QuestionCircleOutlined style={{ color: '#999' }} />
          </Tooltip>
        </Space>
      }
      rules={[
        { required: true, message: t('create.image.required') },
        { pattern: IMAGE_URI_PATTERN, message: t('create.image.format') },
      ]}
      extra={
        loading ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t('create.image.loading')}
          </Typography.Text>
        ) : images.length === 0 ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            <Trans
              i18nKey="create.image.empty"
              ns="dynamo"
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
      <AutoComplete
        options={options}
        allowClear
        placeholder="nvcr.io/nvidia/ai-dynamo/sglang-runtime:1.2.1-efa-amd64"
        filterOption={(input, option) => {
          const q = input.toLowerCase();
          if (images.some((i) => i.image_uri.toLowerCase() === q)) return true;
          return String(option?.value ?? '').toLowerCase().includes(q);
        }}
      />
    </Form.Item>
  );
}
