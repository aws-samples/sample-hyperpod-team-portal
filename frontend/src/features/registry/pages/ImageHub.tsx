import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { PageContainer } from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import PageDescription from '@/shared/ui/PageDescription';
import { ApiError } from '@/shared/api';
import {
  listWorkspaceImages,
  unregisterWorkspaceImage,
  type ImageUse,
  type WorkspaceImage,
} from '@/api/registry';
import RegisterImageModal from '../components/RegisterImageModal';
import BuildImageModal from '../components/BuildImageModal';
import BuildHistory from '../components/BuildHistory';
import { imageUseLabel } from '../mock';

const { Text } = Typography;

type UseFilter = 'all' | ImageUse;

const USE_TAG_COLOR: Record<ImageUse, string> = {
  dev: 'geekblue',
  training: 'green',
  inference: 'purple',
};

/**
 * 镜像中心 (工作空间级)。
 * 管理本 ws 可用镜像 (引用模型): 从 ECR 注册 或 在线构建 (Dockerfile→CodeBuild)
 * → 打用途标签 → 创建任务时按用途选用。
 */
export default function ImageHub() {
  const { t } = useTranslation(['registry', 'common']);
  const { wsId = '' } = useParams();
  const [items, setItems] = useState<WorkspaceImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [useFilter, setUseFilter] = useState<UseFilter>('all');
  const [kw, setKw] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [buildOpen, setBuildOpen] = useState(false);
  // 提交构建后 +1: 联动刷新镜像列表 (build 成功会自动注册进来) 和构建历史
  const [refreshKey, setRefreshKey] = useState(0);
  // 构建中的数量 (BuildHistory 回传), 用于「构建历史」Tab 角标
  const [buildingCount, setBuildingCount] = useState(0);

  const refresh = useCallback(() => {
    if (!wsId) return;
    setLoading(true);
    listWorkspaceImages(wsId)
      .then(setItems)
      .catch((err) => {
        message.error(err instanceof ApiError ? err.message : t('hub.loadFailed'));
        setItems([]);
      })
      .finally(() => setLoading(false));
  }, [wsId, t]);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  const filtered = useMemo(
    () =>
      items.filter((it) => {
        if (useFilter !== 'all' && !it.uses.includes(useFilter)) return false;
        if (kw) {
          const hay = `${it.display_name} ${it.image_uri}`.toLowerCase();
          if (!hay.includes(kw.toLowerCase())) return false;
        }
        return true;
      }),
    [items, useFilter, kw],
  );

  const handleDelete = async (row: WorkspaceImage) => {
    try {
      await unregisterWorkspaceImage(wsId, row.id);
      message.success(t('hub.unregistered'));
      refresh();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : t('hub.unregisterFailed'));
    }
  };

  const columns = [
    {
      title: t('hub.columns.image'),
      key: 'image',
      render: (_: unknown, row: WorkspaceImage) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 13 }}>{row.display_name}</Text>
          <Text type="secondary" style={{ fontSize: 12, fontFamily: 'monospace' }}>
            {row.image_uri}
          </Text>
        </Space>
      ),
    },
    {
      title: t('hub.columns.uses'),
      key: 'uses',
      width: 180,
      render: (_: unknown, row: WorkspaceImage) => (
        <Space size={4} wrap>
          {row.uses.map((u) => (
            <Tag key={u} color={USE_TAG_COLOR[u]} style={{ marginInlineEnd: 0 }}>
              {imageUseLabel(u)}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: t('hub.columns.source'),
      dataIndex: 'source',
      width: 110,
      render: (s: WorkspaceImage['source']) =>
        s === 'ecr-public' ? t('hub.source.public') : t('hub.source.private'),
    },
    {
      title: t('hub.columns.creator'),
      dataIndex: 'creator_username',
      width: 120,
      render: (v: string) => v || '—',
    },
    {
      title: t('common:fields.actions'),
      key: 'action',
      width: 100,
      render: (_: unknown, row: WorkspaceImage) => (
        <Popconfirm
          title={t('hub.unregisterConfirm', { name: row.display_name })}
          description={t('hub.unregisterDesc')}
          onConfirm={() => handleDelete(row)}
          okType="danger"
          okText={t('hub.unregister')}
          cancelText={t('common:actions.cancel')}
        >
          <a style={{ color: '#f5222d' }}>{t('hub.unregister')}</a>
        </Popconfirm>
      ),
    },
  ];

  return (
    <PageContainer
      header={{ title: t('hub.title') }}
      extra={[
        <Button key="build" onClick={() => setBuildOpen(true)}>
          {t('hub.build')}
        </Button>,
        <Button key="register" type="primary" onClick={() => setModalOpen(true)}>
          {t('hub.register')}
        </Button>,
      ]}
    >
      <PageDescription>
        <Trans ns="registry" i18nKey="hub.description" components={{ b: <b /> }} />
      </PageDescription>

      <Tabs
        items={[
          {
            key: 'images',
            label: t('hub.tabs.images'),
            children: (
              <>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 12,
                    gap: 12,
                    flexWrap: 'wrap',
                  }}
                >
                  <Segmented<UseFilter>
                    value={useFilter}
                    onChange={(v) => setUseFilter(v)}
                    options={[
                      { label: t('hub.filterAll'), value: 'all' },
                      { label: imageUseLabel('dev'), value: 'dev' },
                      { label: imageUseLabel('training'), value: 'training' },
                      { label: imageUseLabel('inference'), value: 'inference' },
                    ]}
                  />
                  <Input.Search
                    allowClear
                    placeholder={t('hub.searchPlaceholder')}
                    style={{ width: 260 }}
                    value={kw}
                    onChange={(e) => setKw(e.target.value)}
                  />
                </div>
                <Table
                  rowKey="id"
                  loading={loading}
                  columns={columns}
                  dataSource={filtered}
                  pagination={false}
                  size="small"
                />
              </>
            ),
          },
          {
            key: 'builds',
            label:
              buildingCount > 0 ? (
                <Badge count={buildingCount} size="small" offset={[8, -2]}>
                  {t('hub.tabs.builds')}
                </Badge>
              ) : (
                t('hub.tabs.builds')
              ),
            children: (
              <BuildHistory
                wsId={wsId}
                refreshKey={refreshKey}
                onBuildingCount={setBuildingCount}
              />
            ),
          },
        ]}
      />

      <RegisterImageModal
        wsId={wsId}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onRegistered={refresh}
      />
      <BuildImageModal
        wsId={wsId}
        open={buildOpen}
        onClose={() => setBuildOpen(false)}
        onSubmitted={() => setRefreshKey((k) => k + 1)}
      />
    </PageContainer>
  );
}
