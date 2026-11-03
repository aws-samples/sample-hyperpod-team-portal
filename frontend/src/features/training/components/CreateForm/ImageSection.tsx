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

// 镜像 URI 格式 (宽松): <registry>/<repo>:<tag>。镜像中心含公开镜像
// (public.ecr.aws / docker hub), 故不强限 ECR-私有格式, 仅校验带 tag。
const IMAGE_URI_PATTERN = /^[\w.\-/]+(:[\w.\-]+)$/;

interface Props {
  wsId: string;
}

/**
 * 训练镜像选择 · 单控件 (AutoComplete), 与开发机一致。
 *
 * 下拉列出本 ws 镜像中心里用途含 training 的镜像 (可搜索), 同时支持直接键入任意
 * 镜像 URI。绑 form 的 image 字段。无已注册镜像时提示去「资产管理 → 镜像」注册。
 */
export default function ImageSection({ wsId }: Props) {
  const { t } = useTranslation(['training', 'common']);
  const [images, setImages] = useState<WorkspaceImage[]>([]);
  // 初始 true: 拉取完成前显"加载中", 避免请求返回前闪"暂无可用"。
  const [loading, setLoading] = useState(true);

  // 拉本 ws 镜像中心的镜像, 过滤出用途含 training 的。
  // 抽成 reload: effect 首次调, 刷新按钮也调 (在别处注册新镜像后即时可选, 不清表单)。
  const reload = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    listWorkspaceImages(wsId)
      .then((list) =>
        setImages(list.filter((img) => img.uses.includes('training'))),
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
          {/* 问号 tooltip 文案 (三个创建页统一) */}
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
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            <Trans
              i18nKey="create.image.empty"
              ns="training"
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
          name="image"
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
            placeholder={t('create.image.placeholder')}
            // 输入值正好等于某个完整 URI = 已选中态 (非搜索), 不过滤展示全部;
            // 否则按 URI 子串过滤。
            filterOption={(input, option) => {
              const q = input.toLowerCase();
              if (images.some((i) => i.image_uri.toLowerCase() === q)) return true;
              return String(option?.value ?? '')
                .toLowerCase()
                .includes(q);
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
