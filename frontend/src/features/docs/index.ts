/**
 * docs feature — 产品文档模块。每页中英两套 (pages/zh-CN, pages/en-US), 按当前语言选。
 *
 * 子页面用同一套 DocPage 外壳, 视觉与产品业务页保持一致 (logo 渐变品牌色,
 * PageContainer + PageDescription 顶部, 圆角 12 卡片正文)。
 * 内容遵循"用户视角 + 技术原理"双层叙述: 用 UserBlock / TechBlock 切片。
 */
import { localized } from './localized';
import ZhOverview from './pages/zh-CN/Overview';
import ZhWorkspace from './pages/zh-CN/Workspace';
import ZhPermissions from './pages/zh-CN/Permissions';
import ZhDevInstance from './pages/zh-CN/DevInstance';
import ZhTraining from './pages/zh-CN/Training';
import ZhInference from './pages/zh-CN/Inference';
import ZhLlmd from './pages/zh-CN/Llmd';
import ZhQuota from './pages/zh-CN/Quota';
import ZhRegistry from './pages/zh-CN/Registry';
import ZhSharing from './pages/zh-CN/Sharing';
import ZhSecret from './pages/zh-CN/Secret';
import ZhObservability from './pages/zh-CN/Observability';
import ZhArchitecture from './pages/zh-CN/Architecture';
import ZhFaq from './pages/zh-CN/Faq';
import ZhGpuFaultRunbook from './pages/zh-CN/GpuFaultRunbook';
import EnOverview from './pages/en-US/Overview';
import EnWorkspace from './pages/en-US/Workspace';
import EnPermissions from './pages/en-US/Permissions';
import EnDevInstance from './pages/en-US/DevInstance';
import EnTraining from './pages/en-US/Training';
import EnInference from './pages/en-US/Inference';
import EnLlmd from './pages/en-US/Llmd';
import EnQuota from './pages/en-US/Quota';
import EnRegistry from './pages/en-US/Registry';
import EnSharing from './pages/en-US/Sharing';
import EnSecret from './pages/en-US/Secret';
import EnObservability from './pages/en-US/Observability';
import EnArchitecture from './pages/en-US/Architecture';
import EnFaq from './pages/en-US/Faq';
import EnGpuFaultRunbook from './pages/en-US/GpuFaultRunbook';

export const DocsOverview = localized(ZhOverview, EnOverview);
export const DocsWorkspace = localized(ZhWorkspace, EnWorkspace);
export const DocsPermissions = localized(ZhPermissions, EnPermissions);
export const DocsDevInstance = localized(ZhDevInstance, EnDevInstance);
export const DocsTraining = localized(ZhTraining, EnTraining);
export const DocsInference = localized(ZhInference, EnInference);
export const DocsLlmd = localized(ZhLlmd, EnLlmd);
export const DocsQuota = localized(ZhQuota, EnQuota);
export const DocsRegistry = localized(ZhRegistry, EnRegistry);
export const DocsSharing = localized(ZhSharing, EnSharing);
export const DocsSecret = localized(ZhSecret, EnSecret);
export const DocsObservability = localized(ZhObservability, EnObservability);
export const DocsArchitecture = localized(ZhArchitecture, EnArchitecture);
export const DocsFaq = localized(ZhFaq, EnFaq);
export const DocsGpuFaultRunbook = localized(ZhGpuFaultRunbook, EnGpuFaultRunbook);
