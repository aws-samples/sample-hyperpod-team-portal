import { Badge, Space, type BadgeProps } from 'antd';
import { useTranslation } from 'react-i18next';

/**
 * 「状态（CR Phase）」字段统一渲染 · 开发机 / 推理 / 训练 详情页共用。
 *
 * 内容 = CR phase 徽标 (原始 phase 字符串 + 语义分色) + 「CR 详情」链接。
 * 「CR 详情」打开 status_detail 只读侧边抽屉 (StatusDetailDrawer, 与 Kueue 详情一致从右侧划出) ——
 * 即列表页放大镜 icon 点开看的同一份原始 CR 状态 JSON。
 */
interface CrPhaseFieldProps {
  /** Badge 颜色 (调用方用 phaseColor 等算好) */
  status: BadgeProps['status'];
  /** 展示文案 (原始 CR phase 字符串, 空时调用方传 "-") */
  text: string;
  /** 点击「CR 详情」打开 status_detail 弹窗 */
  onShowDetail: () => void;
}

export default function CrPhaseField({ status, text, onShowDetail }: CrPhaseFieldProps) {
  const { t } = useTranslation('common');
  return (
    <Space size={8}>
      <Badge status={status} text={text} />
      <a onClick={onShowDetail}>{t('crPhase.detailLink')}</a>
    </Space>
  );
}
