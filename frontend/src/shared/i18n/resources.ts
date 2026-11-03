/** 20 个命名空间 × 2 语言, 静态打包 (不懒加载, 避免切换时闪 key)。新增 ns: 两边各加一行 import + 一个字段。 */
import zhCommon from './locales/zh-CN/common.json';
import zhLayout from './locales/zh-CN/layout.json';
import zhStatus from './locales/zh-CN/status.json';
import zhAuth from './locales/zh-CN/auth.json';
import zhWorkspace from './locales/zh-CN/workspace.json';
import zhDevinstance from './locales/zh-CN/devinstance.json';
import zhTraining from './locales/zh-CN/training.json';
import zhRayjob from './locales/zh-CN/rayjob.json';
import zhInference from './locales/zh-CN/inference.json';
import zhLlmd from './locales/zh-CN/llmd.json';
import zhDynamo from './locales/zh-CN/dynamo.json';
import zhTasks from './locales/zh-CN/tasks.json';
import zhAdmin from './locales/zh-CN/admin.json';
import zhQuota from './locales/zh-CN/quota.json';
import zhRegistry from './locales/zh-CN/registry.json';
import zhSecret from './locales/zh-CN/secret.json';
import zhSharing from './locales/zh-CN/sharing.json';
import zhLogs from './locales/zh-CN/logs.json';
import zhMonitoring from './locales/zh-CN/monitoring.json';
import zhDocs from './locales/zh-CN/docs.json';
import enCommon from './locales/en-US/common.json';
import enLayout from './locales/en-US/layout.json';
import enStatus from './locales/en-US/status.json';
import enAuth from './locales/en-US/auth.json';
import enWorkspace from './locales/en-US/workspace.json';
import enDevinstance from './locales/en-US/devinstance.json';
import enTraining from './locales/en-US/training.json';
import enRayjob from './locales/en-US/rayjob.json';
import enInference from './locales/en-US/inference.json';
import enLlmd from './locales/en-US/llmd.json';
import enDynamo from './locales/en-US/dynamo.json';
import enTasks from './locales/en-US/tasks.json';
import enAdmin from './locales/en-US/admin.json';
import enQuota from './locales/en-US/quota.json';
import enRegistry from './locales/en-US/registry.json';
import enSecret from './locales/en-US/secret.json';
import enSharing from './locales/en-US/sharing.json';
import enLogs from './locales/en-US/logs.json';
import enMonitoring from './locales/en-US/monitoring.json';
import enDocs from './locales/en-US/docs.json';

export const defaultNS = 'common' as const;

export const resources = {
  'zh-CN': {
    common: zhCommon, layout: zhLayout, status: zhStatus, auth: zhAuth, workspace: zhWorkspace,
    devinstance: zhDevinstance, training: zhTraining, rayjob: zhRayjob, inference: zhInference,
    llmd: zhLlmd, dynamo: zhDynamo, tasks: zhTasks, admin: zhAdmin, quota: zhQuota,
    registry: zhRegistry, secret: zhSecret, sharing: zhSharing, logs: zhLogs,
    monitoring: zhMonitoring, docs: zhDocs,
  },
  'en-US': {
    common: enCommon, layout: enLayout, status: enStatus, auth: enAuth, workspace: enWorkspace,
    devinstance: enDevinstance, training: enTraining, rayjob: enRayjob, inference: enInference,
    llmd: enLlmd, dynamo: enDynamo, tasks: enTasks, admin: enAdmin, quota: enQuota,
    registry: enRegistry, secret: enSecret, sharing: enSharing, logs: enLogs,
    monitoring: enMonitoring, docs: enDocs,
  },
} as const;
