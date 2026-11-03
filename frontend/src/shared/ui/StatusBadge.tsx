import { Badge } from 'antd';
import { phaseColor, phaseLabel } from '@/shared/status';

/**
 * 全局任务状态徽章 (跨 feature 复用).
 * 接收原始 CR phase 字符串, 映射成 Badge 颜色 + 中文 label (未命中原样显示).
 */
export default function StatusBadge({ status }: { status: string | null }) {
  return <Badge status={phaseColor(status)} text={phaseLabel(status)} />;
}
