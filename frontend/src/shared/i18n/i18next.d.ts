import 'i18next';
import type { defaultNS, resources } from './resources';

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: typeof defaultNS;
    // 以 zh-CN 结构为 key 真相源: key 拼错编译报错 (en-US 缺 key 由 check-i18n 守门拦)。
    resources: (typeof resources)['zh-CN'];
  }
}
