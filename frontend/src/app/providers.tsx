/**
 * App-level providers (AntD ConfigProvider + theme token + locale).
 *
 * Wave 1 skeleton: this file is **not yet wired up**. `App.tsx` still hosts
 * the ConfigProvider directly. Wave 3 will:
 *   1. Move the provider stack from `App.tsx` into `<AppProviders>`.
 *   2. Have `App.tsx` simply render `<AppProviders><AppRouter /></AppProviders>`.
 *   3. Add a Zustand store provider here if we ever need context-based
 *      store scoping (e.g. per-workspace isolated stores in tests).
 *
 * Keeping this file as a living reference lets the Wave 3 migration be a
 * drop-in edit rather than a new file + import churn in `main.tsx`.
 */
import type { PropsWithChildren } from 'react';
import { useEffect } from 'react';
import { ConfigProvider, App as AntdApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useAppStore } from '@/store';
import { buildThemeConfig } from '@/theme/token';

export function AppProviders({ children }: PropsWithChildren) {
  const themeMode = useAppStore((s) => s.themeMode);

  // Mirror the current theme mode to a `data-theme` attribute on <html> so
  // our CSS (shadows, accents, Monaco wrapper, etc.) can adapt without
  // relying on AntD's internal class hashing.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', themeMode);
    document.body.style.colorScheme = themeMode;
  }, [themeMode]);

  return (
    <ConfigProvider locale={zhCN} theme={buildThemeConfig(themeMode)}>
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
