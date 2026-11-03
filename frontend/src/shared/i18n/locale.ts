/** 语言集与首次判定 (spec §2 严格规则: 恰好 zh-CN 才是中文, 其余一律 en-US)。纯函数, 不依赖 i18next。 */
export const SUPPORTED_LOCALES = ['zh-CN', 'en-US'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en-US';
export const LOCALE_STORAGE_KEY = 'hp.lang';

export function isLocale(v: unknown): v is Locale {
  return v === 'zh-CN' || v === 'en-US';
}

/** localStorage 有合法值用它; 否则仅 navigator.language === 'zh-CN' 为中文。 */
export function resolveInitialLocale(): Locale {
  try {
    const saved = localStorage.getItem(LOCALE_STORAGE_KEY);
    if (isLocale(saved)) return saved;
  } catch {
    // 隐私模式等 localStorage 不可用: 退回浏览器语言
  }
  return navigator.language === 'zh-CN' ? 'zh-CN' : 'en-US';
}

export function persistLocale(locale: Locale): void {
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // 写不进就只本次生效
  }
}
