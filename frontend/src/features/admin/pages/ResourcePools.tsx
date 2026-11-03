import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Modal,
  Progress,
  Row,
  Space,
  Tag,
  Typography,
  message,
  theme,
} from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  ClusterOutlined,
  EyeOutlined,
  PauseCircleOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { mockResourcePools, type ResourcePool } from '@/mock/infra';
import { mockWorkspaces } from '@/mock/workspaces';

const { Text } = Typography;

/** Map a pool role to an accent color for the card's top border. */
const roleAccent = (role: ResourcePool['role']): string => {
  switch (role) {
    case 'gpu-h100':
      return '#f5222d';
    case 'gpu-a100':
      return '#fa8c16';
    case 'dedicated':
      return '#722ed1';
    default:
      return '#0958d9';
  }
};

const workspaceNameOf = (id: string): string =>
  mockWorkspaces.find((w) => w.id === id)?.displayName ?? id;

interface PoolCardProps {
  pool: ResourcePool;
  onAction: (poolId: string, action: string) => void;
}

const PoolCard = ({ pool, onAction }: PoolCardProps) => {
  const { token } = theme.useToken();
  const accent = roleAccent(pool.role);
  const usagePct =
    pool.gpuTotal === 0
      ? Math.round((pool.nodeTotal - pool.nodeAvailable) / pool.nodeTotal * 100)
      : Math.round((pool.gpuAllocated / pool.gpuTotal) * 100);
  const unit = pool.gpuTotal === 0 ? '节点' : 'GPU';
  const usedOfTotal =
    pool.gpuTotal === 0
      ? `${pool.nodeTotal - pool.nodeAvailable} / ${pool.nodeTotal}`
      : `${pool.gpuAllocated} / ${pool.gpuTotal}`;

  return (
    <Card
      hoverable
      style={{
        borderRadius: 12,
        borderTop: `3px solid ${accent}`,
        height: '100%',
      }}
      styles={{ body: { padding: 20 } }}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <ClusterOutlined style={{ color: accent, fontSize: 18 }} />
            <Text strong style={{ fontSize: 15 }}>
              {pool.displayName}
            </Text>
          </Space>
          <Badge
            status={pool.status === 'Active' ? 'success' : 'warning'}
            text={pool.status}
          />
        </Space>

        <Text type="secondary" style={{ fontSize: 12 }}>
          {pool.description}
        </Text>

        <Space wrap size={6}>
          <Tag color="geekblue">{pool.instanceType}</Tag>
          <Tag>
            节点 {pool.nodeAvailable} / {pool.nodeTotal}
          </Tag>
        </Space>

        <div>
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {unit} 分配
            </Text>
            <Text strong style={{ fontSize: 12 }}>
              {usedOfTotal}
            </Text>
          </Space>
          <Progress
            percent={usagePct}
            showInfo={false}
            strokeColor={accent}
            style={{ marginTop: 4 }}
          />
        </div>

        {pool.gpuTotal > 0 && (
          <Space size={8} wrap>
            <Tag icon={<ThunderboltOutlined />} color="processing">
              已分配 {pool.gpuAllocated}
            </Tag>
            <Tag color="default">空闲 {pool.gpuTotal - pool.gpuAllocated}</Tag>
            {pool.gpuQueued > 0 && (
              <Tag color="warning">排队 {pool.gpuQueued}</Tag>
            )}
          </Space>
        )}

        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Kueue 队列
          </Text>
          <div style={{ marginTop: 4 }}>
            <Tag color="cyan">{pool.kueueQueue}</Tag>
          </div>
        </div>

        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            授权 Workspace ({pool.grantedWorkspaces.length})
          </Text>
          <div style={{ marginTop: 4 }}>
            <Space size={4} wrap>
              {pool.grantedWorkspaces.map((id) => (
                <Tag key={id} color="blue">
                  {workspaceNameOf(id)}
                </Tag>
              ))}
            </Space>
          </div>
        </div>

        <Space
          size={6}
          style={{
            width: '100%',
            justifyContent: 'flex-end',
            paddingTop: 8,
            borderTop: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Button
            size="small"
            icon={<ArrowUpOutlined />}
            onClick={() => onAction(pool.id, 'scale-up')}
          >
            扩容
          </Button>
          <Button
            size="small"
            icon={<ArrowDownOutlined />}
            onClick={() => onAction(pool.id, 'scale-down')}
          >
            缩容
          </Button>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => onAction(pool.id, 'view')}
          >
            节点
          </Button>
          <Button
            size="small"
            danger
            icon={<PauseCircleOutlined />}
            onClick={() => onAction(pool.id, 'pause')}
          >
            暂停
          </Button>
        </Space>
      </Space>
    </Card>
  );
};

export default function AdminResourcePools() {
  const [creating, setCreating] = useState(false);

  const handleAction = (poolId: string, action: string) => {
    message.info(`${action} on ${poolId} (原型,暂未联动后端)`);
  };

  return (
    <PageContainer
      title="计算资源池"
      subTitle="将 Instance Group 封装为可分配的资源池,统一做配额和队列绑定"
      extra={[
        <Button
          key="new"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreating(true)}
        >
          新建资源池
        </Button>,
      ]}
    >
      <Row gutter={[16, 16]}>
        {mockResourcePools.map((pool) => (
          <Col key={pool.id} xs={24} md={12} xl={8}>
            <PoolCard pool={pool} onAction={handleAction} />
          </Col>
        ))}
      </Row>

      <Modal
        title="新建资源池"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => {
          message.success('已提交创建请求 (原型占位)');
          setCreating(false);
        }}
      >
        <Text type="secondary">
          选择底层 Instance Group 或创建新的 SageMaker HyperPod Instance Group,
          绑定 Kueue ClusterQueue,然后授权给一个或多个 Workspace。
        </Text>
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            原型阶段:此处可扩展为 Form,当前仅占位。
          </Text>
        </div>
      </Modal>
    </PageContainer>
  );
}
