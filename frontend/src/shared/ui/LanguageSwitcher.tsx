import { Dropdown } from 'antd';
import { GlobalOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { SUPPORTED_LOCALES, currentLocale, switchLocale, type Locale } from '@/shared/i18n';

/** 顶栏语言切换: 选中即写 localStorage 并整页刷新 (后端下发文案随之按新语言重拉)。 */
export default function LanguageSwitcher() {
  const { t } = useTranslation();
  const cur = currentLocale();
  return (
    <Dropdown
      trigger={['click']}
      menu={{
        selectable: true,
        selectedKeys: [cur],
        items: SUPPORTED_LOCALES.map((l) => ({ key: l, label: t(`language.${l}`) })),
        onClick: ({ key }) => switchLocale(key as Locale),
      }}
    >
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 13,
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
      >
        <GlobalOutlined style={{ color: 'rgba(0,0,0,0.45)' }} />
        {t(`language.${cur}`)}
      </span>
    </Dropdown>
  );
}
