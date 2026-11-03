import { Col, Row, Space, Typography } from 'antd';
import type { ResourcePoolOption } from '@/mock/assets';

const { Text } = Typography;

interface Props {
  /** Currently selected resource pool; optional so the bar can still render with placeholder values. */
  pool?: ResourcePoolOption;
  /** GPU count this submission will consume. */
  requestGpu: number;
  /** Node count this submission will consume. */
  requestNodes: number;
  /** Workspace total GPU quota. */
  wsQuotaGpu: number;
  /** Workspace GPU already used by other running tasks. Pass `-1` as a
   *  sentinel when usage data is unavailable (Kueue endpoint degraded). */
  wsUsedGpu: number;
}

/**
 * Sticky quota preview bar shown on every step of the create form.
 * Shows pool occupancy, workspace quota remaining, and this submission's impact.
 *
 * Wave 3 (C3) migration: moved from `src/components/common/QuotaPreviewBar.tsx`
 * into the quota feature since it's quota-specific UI.
 */
export default function QuotaPreviewBar({
  pool,
  requestGpu,
  requestNodes,
  wsQuotaGpu,
  wsUsedGpu,
}: Props) {
  const poolFree = pool ? pool.totalGpu - pool.usedGpu : 0;
  const poolFreePct = pool
    ? Math.round(((pool.totalGpu - pool.usedGpu) / pool.totalGpu) * 100)
    : 0;
  // Sentinel: wsUsedGpu < 0 means usage endpoint unavailable — cannot
  // compute remaining/overQuota, so degrade to "采集中" display.
  const usageAvailable = wsUsedGpu >= 0;
  const wsRemaining = usageAvailable
    ? Math.max(0, wsQuotaGpu - wsUsedGpu)
    : 0;
  const overQuota = usageAvailable && requestGpu > wsRemaining;
  const overPool = pool ? requestGpu > poolFree : false;

  return (
    <div
      style={{
        borderTop: '1px dashed #d9d9d9',
        borderBottom: '1px dashed #d9d9d9',
        padding: '8px 16px',
        margin: '8px 0',
        background: 'rgba(22,119,255,0.03)',
      }}
    >
      <Row gutter={24} align="middle">
        <Col flex="auto">
          <Space size="large" wrap>
            <Text>
              本次将占用:
              <Text strong style={{ color: overPool ? '#cf1322' : '#1677ff' }}>
                {' '}
                {requestGpu} GPU · {requestNodes} 节点
              </Text>
            </Text>
            <Text>
              资源池剩余:
              <Text strong style={{ color: overPool ? '#cf1322' : undefined }}>
                {' '}
                {poolFree} GPU({poolFreePct}% 可用)
              </Text>
            </Text>
            <Text>
              工作空间配额剩余:
              <Text strong style={{ color: overQuota ? '#cf1322' : undefined }}>
                {' '}
                {usageAvailable
                  ? `${wsRemaining} GPU / ${wsQuotaGpu} GPU`
                  : `配额 ${wsQuotaGpu} GPU · 剩余采集中`}
              </Text>
            </Text>
          </Space>
        </Col>
        {(overPool || overQuota) && (
          <Col>
            <Text type="danger" style={{ fontSize: 12 }}>
              {overPool && '资源池 GPU 不足;'}
              {overQuota && '工作空间配额不足。'}
            </Text>
          </Col>
        )}
      </Row>
    </div>
  );
}
