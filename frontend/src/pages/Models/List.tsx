import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer, ProCard } from '@ant-design/pro-components';
import {
  App,
  Button,
  Col,
  Drawer,
  Empty,
  Input,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  CloudDownloadOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  PlusOutlined,
  RocketOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { mockModels, type ModelAsset, type ModelSource } from '@/mock/assets';

const { Text, Paragraph } = Typography;

const SOURCE_META: Record<ModelSource, { label: string; color: string }> = {
  training: { label: '训练产物', color: 'purple' },
  huggingface: { label: 'HuggingFace', color: 'gold' },
  upload: { label: '本地上传', color: 'blue' },
};

export default function ModelsList() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [keyword, setKeyword] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState<ModelSource>('training');

  const wsModels = useMemo(
    () => mockModels.filter((m) => m.workspaceId === wsId),
    [wsId],
  );

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return wsModels;
    return wsModels.filter(
      (m) =>
        m.name.toLowerCase().includes(kw) ||
        m.baseModel.toLowerCase().includes(kw),
    );
  }, [wsModels, keyword]);

  const kpis = useMemo(() => {
    const total = wsModels.length;
    const trained = wsModels.filter((m) => m.source === 'training').length;
    const totalGb = Math.round(wsModels.reduce((sum, m) => sum + m.sizeGb, 0));
    return { total, trained, totalGb };
  }, [wsModels]);

  const handleDeploy = (m: ModelAsset) => {
    navigate(
      `/workspaces/${wsId}/inference/new?model=${encodeURIComponent(m.id)}`,
    );
  };

  return (
    <PageContainer
      header={{
        title: '模型仓库',
        breadcrumb: {
          items: [{ title: 'Workspace' }, { title: '模型仓库' }],
        },
      }}
      extra={[
        <Input.Search
          key="search"
          placeholder="搜索模型名 / 基础模型"
          allowClear
          style={{ width: 260 }}
          onChange={(e) => setKeyword(e.target.value)}
        />,
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setDrawerOpen(true)}
        >
          新增模型
        </Button>,
      ]}
    >
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}>
          <ProCard>
            <Statistic
              title="模型总数"
              value={kpis.total}
              prefix={<DatabaseOutlined style={{ color: '#1677ff' }} />}
            />
          </ProCard>
        </Col>
        <Col xs={24} md={8}>
          <ProCard>
            <Statistic
              title="训练产物"
              value={kpis.trained}
              prefix={<ExperimentOutlined style={{ color: '#722ed1' }} />}
            />
          </ProCard>
        </Col>
        <Col xs={24} md={8}>
          <ProCard>
            <Statistic
              title="总大小 (GB)"
              value={kpis.totalGb}
              precision={0}
              prefix={<DeploymentUnitOutlined style={{ color: '#13c2c2' }} />}
            />
          </ProCard>
        </Col>
      </Row>

      {filtered.length === 0 ? (
        <ProCard>
          <Empty description="当前工作空间暂无模型" />
        </ProCard>
      ) : (
        <Row gutter={[16, 16]}>
          {filtered.map((m) => {
            const srcMeta = SOURCE_META[m.source];
            return (
              <Col key={m.id} xs={24} md={12} xl={8}>
                <ProCard
                  title={
                    <Space size={6}>
                      <Text strong>{m.name}</Text>
                      <Tag color="blue">{m.version}</Tag>
                    </Space>
                  }
                  extra={<Tag color={srcMeta.color}>{srcMeta.label}</Tag>}
                  bordered
                  hoverable
                >
                  <Space direction="vertical" style={{ width: '100%' }} size={4}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      基础模型
                    </Text>
                    <Text style={{ fontSize: 13 }}>{m.baseModel}</Text>
                    <Row gutter={8} style={{ marginTop: 4 }}>
                      <Col span={12}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          大小
                        </Text>
                        <div>
                          <Text strong>{m.sizeGb.toFixed(1)} GB</Text>
                        </div>
                      </Col>
                      <Col span={12}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          精度
                        </Text>
                        <div>
                          <Tag>{m.precision}</Tag>
                        </div>
                      </Col>
                    </Row>
                    <Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
                      FSx 路径
                    </Text>
                    <Paragraph
                      style={{ fontSize: 12, margin: 0 }}
                      copyable
                      ellipsis={{ rows: 1 }}
                    >
                      {m.fsxPath}
                    </Paragraph>
                    <Row gutter={8} style={{ marginTop: 4 }}>
                      <Col span={12}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          创建者
                        </Text>
                        <div style={{ fontSize: 12 }}>{m.creator}</div>
                      </Col>
                      <Col span={12}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          创建时间
                        </Text>
                        <div style={{ fontSize: 12 }}>
                          {dayjs(m.createdAt).format('MM-DD HH:mm')}
                        </div>
                      </Col>
                    </Row>
                    <Space
                      wrap
                      style={{
                        marginTop: 12,
                        paddingTop: 12,
                        borderTop: '1px dashed #e6e6e6',
                        width: '100%',
                      }}
                    >
                      <Button
                        size="small"
                        onClick={() => message.info(`查看详情：${m.name}（占位）`)}
                      >
                        查看详情
                      </Button>
                      <Button
                        size="small"
                        type="primary"
                        icon={<RocketOutlined />}
                        onClick={() => handleDeploy(m)}
                      >
                        部署推理
                      </Button>
                      <Button
                        size="small"
                        icon={<CloudDownloadOutlined />}
                        onClick={() => message.success(`已开始下载 ${m.name}`)}
                      >
                        下载
                      </Button>
                      <Popconfirm
                        title={`确认删除 ${m.name}？`}
                        onConfirm={() => message.warning(`已删除 ${m.name}（占位）`)}
                      >
                        <Button size="small" danger>
                          删除
                        </Button>
                      </Popconfirm>
                    </Space>
                  </Space>
                </ProCard>
              </Col>
            );
          })}
        </Row>
      )}

      <Drawer
        title="新增模型"
        width={540}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <Tabs
          activeKey={drawerTab}
          onChange={(k) => setDrawerTab(k as ModelSource)}
          items={[
            {
              key: 'training',
              label: '训练产物',
              children: (
                <Empty description="从训练任务列表中选择产出目录（占位）">
                  <Button type="primary" icon={<ExperimentOutlined />}>
                    浏览训练任务
                  </Button>
                </Empty>
              ),
            },
            {
              key: 'huggingface',
              label: 'HuggingFace 下载',
              children: (
                <Empty description="输入 model-id，后台将异步下载到 FSx（占位）">
                  <Button type="primary" icon={<CloudDownloadOutlined />}>
                    开始下载
                  </Button>
                </Empty>
              ),
            },
            {
              key: 'upload',
              label: '本地上传',
              children: (
                <Empty description="通过 S3 分片上传到 FSx（占位）">
                  <Button type="primary" icon={<UploadOutlined />}>
                    选择文件
                  </Button>
                </Empty>
              ),
            },
          ]}
        />
      </Drawer>
    </PageContainer>
  );
}
