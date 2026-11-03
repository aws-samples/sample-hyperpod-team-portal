/**
 * 前端 i18n 入口 (贡献者指南见 docs/i18n-glossary.md §0)。
 *
 * main.tsx 必须先于 App import 本模块: 求值时同步完成初始化 (资源静态打包 + initAsync:false),
 * 之后任何模块的 i18n.t / useTranslation 都可直接用。语言在一次页面生命周期内恒定:
 * 切换 = 写 localStorage + 整页刷新 (让后端下发的文案也按新语言重拉)。
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import {
  DEFAULT_LOCALE,
  SUPPORTED_LOCALES,
  isLocale,
  persistLocale,
  resolveInitialLocale,
  type Locale,
} from './locale';
import { defaultNS, resources } from './resources';

const initial = resolveInitialLocale();

void i18n.use(initReactI18next).init({
  resources,
  lng: initial,
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: [...SUPPORTED_LOCALES],
  load: 'currentOnly',
  defaultNS,
  ns: Object.keys(resources['zh-CN']),
  initAsync: false,
  interpolation: { escapeValue: false }, // React 已转义
  react: { useSuspense: false },
});

dayjs.locale(initial === 'zh-CN' ? 'zh-cn' : 'en');
document.documentElement.lang = initial;

export function currentLocale(): Locale {
  return isLocale(i18n.language) ? i18n.language : initial;
}

export function switchLocale(next: Locale): void {
  if (next === currentLocale()) return;
  persistLocale(next);
  window.location.reload();
}

/** EventSource / WebSocket / 下载链接设不了请求头, 用 ?lang= 传语言 (后端 LocaleMiddleware 认它)。 */
export function withLang(url: string): string {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}lang=${encodeURIComponent(currentLocale())}`;
}

export { SUPPORTED_LOCALES, type Locale } from './locale';
export default i18n;
