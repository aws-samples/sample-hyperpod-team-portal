import { theme as antdTheme, type ThemeConfig } from 'antd';
import type { ThemeMode } from '@/store';

/**
 * Shared AntD theme tokens. Tuned to look more enterprise-grade than the
 * default Geek Blue — deeper primary, softer layout bg, slightly larger radius.
 *
 * Font-family note: we name `"Inter"` first, but intentionally do NOT ship a
 * webfont — browsers will silently fall back to the system UI stack if Inter
 * is not installed. This keeps the bundle small while letting any user who has
 * Inter installed (most designers/engineers do) get the preferred rendering.
 */
export const FONT_FAMILY_STACK =
  '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';

export const buildThemeConfig = (mode: ThemeMode): ThemeConfig => {
  const isDark = mode === 'dark';
  return {
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: '#0958d9',
      colorInfo: '#0958d9',
      colorSuccess: '#389e0d',
      colorWarning: '#d48806',
      colorError: '#cf1322',
      colorBgLayout: isDark ? '#0f1419' : '#f5f7fa',
      borderRadius: 8,
      wireframe: false,
      fontSize: 14,
      fontFamily: FONT_FAMILY_STACK,
    },
    components: {
      Layout: {
        bodyBg: isDark ? '#0f1419' : '#f5f7fa',
        headerBg: isDark ? '#001529' : '#ffffff',
        siderBg: isDark ? '#001529' : '#ffffff',
      },
      Menu: {
        itemHeight: 40,
        itemSelectedBg: isDark ? 'rgba(9, 88, 217, 0.15)' : '#e6f0ff',
        itemSelectedColor: isDark ? '#69b1ff' : '#0958d9',
      },
      Card: {
        borderRadiusLG: 12,
      },
      Table: {
        cellPaddingBlock: 12,
        cellPaddingInline: 16,
        headerBg: isDark ? '#141a21' : '#fafbfc',
      },
      Button: {
        controlHeight: 34,
        fontWeight: 500,
      },
      Tooltip: {
        // 全局统一: 浅色 tooltip (白底深字), 替代默认刺眼黑底。
        // 业务里直接用 <Tooltip>/Form.Item tooltip 即可, 无需逐处传 color/styles。
        colorBgSpotlight: isDark ? '#1f1f1f' : '#ffffff',
        colorTextLightSolid: isDark
          ? 'rgba(255,255,255,0.85)'
          : 'rgba(0,0,0,0.85)',
      },
    },
  };
};
