import { Badge, Space, Tooltip, Typography } from 'antd';
import { useTranslation } from 'react-i18next';
import { kueueStatusColor, kueueStatusLabel } from '@/shared/status';

/**
 * 「排队状态（Kueue）」字段统一渲染 · 开发机 / 推理 / 训练 详情页共用。
 *
 * 内容 = Kueue 六态徽标 (Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished,
 * Workload 字段镜像, 原始英文值 + 语义分色) + 「Kueue 详情」链接 (打开实时 Workload 抽屉)。
 *
 * - 无 kueue_status (空/未知, 如未排队/终态): 徽标位显 "-", 链接仍保留 (可查实时 Workload)。
 * - Queued 态额外挂 tooltip 解释排队语义。
 */
interface KueueStatusFieldProps {
  /** kueue_status 原始值 (Workload 六态镜像); 空/未知显 "-" */
  status: string | null | undefined;
  /** 点击「Kueue 详情」打开实时 Workload 抽屉 */
  onShowDetail: () => void;
}

export default function KueueStatusField({ status, onShowDetail }: KueueStatusFieldProps) {
  const { t } = useTranslation('common');
  const label = kueueStatusLabel(status);
  const badge = label ? (
    <Badge status={kueueStatusColor(status)} text={label} />
  ) : (
    <Typography.Text type="secondary">-</Typography.Text>
  );

  return (
    <Space size={8}>
      {status === 'Queued' ? (
        <Tooltip title={t('kueueStatus.queuedTip')}>{badge}</Tooltip>
      ) : (
        badge
      )}
      <a onClick={onShowDetail}>{t('kueueStatus.detailLink')}</a>
    </Space>
  );
}
