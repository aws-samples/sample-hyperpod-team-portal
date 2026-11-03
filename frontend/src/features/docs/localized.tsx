import type { ComponentType } from 'react';
import { currentLocale } from '@/shared/i18n';

/** 文档页按当前语言选组件 (语言在页面生命周期内恒定, 模块求值时选定即可)。 */
export function localized(zh: ComponentType, en: ComponentType): ComponentType {
  return currentLocale() === 'zh-CN' ? zh : en;
}
