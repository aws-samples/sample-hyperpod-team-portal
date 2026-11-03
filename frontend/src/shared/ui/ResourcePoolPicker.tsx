import { Badge, Col, Row, Space, Tag, Typography } from 'antd';
import type { ResourcePoolOption } from '@/mock/assets';

const { Text } = Typography;

const POOL_COLOR: Record<ResourcePoolOption['poolType'], string> = {
  general: 'blue',
  'gpu-h100': 'geekblue',
  'gpu-a100': 'purple',
  dedicated: 'gold',
};

const STATUS_BADGE: Record<
  ResourcePoolOption['status'],
  { color: string; text: string }
> = {
  available: { color: 'green', text: '可用' },
  busy: { color: 'orange', text: '繁忙' },
  offline: { color: 'red', text: '离线' },
};

interface Props {
  pools: ResourcePoolOption[];
  value?: string;
  onChange?: (id: string) => void;
}

/**
 * 计算资源池选择器 (卡片式 radio group).
 * Training / Inference / DevInstance 三处 Create 流程 Step 1 共用.
 */
export default function ResourcePoolPicker({ pools, value, onChange }: Props) {
  return (
    <Row gutter={[12, 12]}>
      {pools.map((p) => {
        const selected = p.id === value;
        const disabled = p.status === 'offline';
        const statusMeta = STATUS_BADGE[p.status];
        const freeGpu = p.totalGpu - p.usedGpu;
        const usagePct = Math.round((p.usedGpu / p.totalGpu) * 100);
        return (
          <Col key={p.id} xs={24} sm={12} xl={6}>
            <div
              onClick={() => !disabled && onChange?.(p.id)}
              style={{
                border: `1.5px solid ${selected ? '#1677ff' : '#e6e6e6'}`,
                background: selected ? 'rgba(22,119,255,0.04)' : 'transparent',
                borderRadius: 8,
                padding: 16,
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.5 : 1,
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                transition: 'all 0.15s ease',
              }}
            >
              <Space size={6} align="center" style={{ marginBottom: 2 }}>
                <Tag color={POOL_COLOR[p.poolType]} style={{ margin: 0 }}>
                  {p.displayName}
                </Tag>
                <Badge color={statusMeta.color} text={statusMeta.text} />
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {p.instanceType}
              </Text>
              <Text style={{ fontSize: 12 }}>
                节点 {p.availableNodes} / {p.nodeCount} 可用
              </Text>
              <Text style={{ fontSize: 12 }}>
                GPU {p.usedGpu} / {p.totalGpu}（空闲 {freeGpu}，占用 {usagePct}%）
              </Text>
              <Text style={{ fontSize: 12 }}>排队任务：{p.queuedTasks}</Text>
              <div
                style={{
                  marginTop: 'auto',
                  paddingTop: 8,
                  textAlign: 'center',
                  fontWeight: 600,
                  color: selected ? '#1677ff' : '#888',
                }}
              >
                {selected ? '[ 当前选中 ]' : '[ 选择 ]'}
              </div>
            </div>
          </Col>
        );
      })}
    </Row>
  );
}
