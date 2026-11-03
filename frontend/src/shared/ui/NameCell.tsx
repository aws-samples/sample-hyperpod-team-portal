import { Link } from 'react-router-dom';
import { Space, Typography } from 'antd';
import { useTranslation } from 'react-i18next';

// 列表「名称」列双行渲染: 第一行展示名 (超链接跳详情), 第二行任务名 (= k8s CR 名)。
// 任务名非链接、灰色、与展示名同字号, 带复制图标。display_name 为空时第一行回退显示
// 任务名 (两行照常显示以保证行高一致)。
export default function NameCell({
  to,
  displayName,
  taskName,
}: {
  to: string;
  displayName?: string | null;
  taskName: string;
}) {
  const { t } = useTranslation('common');
  return (
    <Space direction="vertical" size={0}>
      <Link to={to}>{displayName || taskName}</Link>
      <Typography.Text
        type="secondary"
        copyable={{ text: taskName, tooltips: [t('actions.copy'), t('messages.copied')] }}
        onClick={(e) => e.stopPropagation()}
      >
        {taskName}
      </Typography.Text>
    </Space>
  );
}
