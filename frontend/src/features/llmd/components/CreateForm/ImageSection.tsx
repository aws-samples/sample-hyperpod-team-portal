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

const DEFAULT_SGLANG_IMAGE = 'lmsysorg/sglang:v0.5.13.post1';

const IMAGE_URI_PATTERN = /^[\w.\-/]+(:[\w.\-]+)$/;

interface Props {
  wsId: string;
}

/**
 * llm-d SGLang worker 镜像选择: AutoComplete 下拉镜像中心 (uses 含 inference)
 * + 可键入任意 URI。绑 form 的 sglang_image 字段, 默认给标准 lmsysorg/sglang 镜像。
 */
export default function ImageSection({ wsId }: Props) {
  const { t } = useTranslation(['llmd', 'common']);
  const [images, setImages] = useState<WorkspaceImage[]>([]);
  const [loading, setLoading] = useState(true);

  // 抽成 reload: effect 首次调, 镜像右侧刷新按钮也调 (别处注册新镜像后即时可选, 不清表单)。
  const reload = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    listWorkspaceImages(wsId)
      .then((list) =>
        setImages(list.filter((img) => img.uses.includes('inference'))),
      )
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
          {t('create.image.label')}
          <Tooltip title={t('create.image.help')}>
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
              ns="llmd"
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
        {/* 内层 noStyle Form.Item 带 name 直接包住 AutoComplete 以保留 form 绑定
            (裸 div 做 Form.Item 直接子元素会吃掉注入的 value/onChange)。 */}
        <Form.Item
          name="sglang_image"
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
            placeholder={DEFAULT_SGLANG_IMAGE}
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
