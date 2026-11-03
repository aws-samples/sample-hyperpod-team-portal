import { useEffect } from 'react';
import { ConfigProvider, App as AntdApp } from 'antd';
import enUS from 'antd/locale/en_US';
import zhCN from 'antd/locale/zh_CN';
import AppRouter from '@/router';
import { useAppStore } from '@/store';
import { currentLocale } from '@/shared/i18n';
import { buildThemeConfig } from '@/theme/token';

// 语言在页面生命周期内恒定 (切换走整页刷新), 模块级取一次即可。
// ProComponents 按 antd locale 自动映射 (pro-provider findIntlKeyByAntdLocaleKey), 无需单独配。
const ANTD_LOCALE = currentLocale() === 'zh-CN' ? zhCN : enUS;

export default function App() {
  const themeMode = useAppStore((s) => s.themeMode);

  /**
   * Mirror the current theme mode to a `data-theme` attribute on the document
   * root so our CSS (shadows, accents, Monaco wrapper, etc.) can adapt without
   * relying on AntD's internal class hashing.
   */
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', themeMode);
    document.body.style.colorScheme = themeMode;
  }, [themeMode]);

  return (
    <ConfigProvider locale={ANTD_LOCALE} theme={buildThemeConfig(themeMode)}>
      <AntdApp>
        <AppRouter />
      </AntdApp>
    </ConfigProvider>
  );
}
