/**
 * 资源模板 API · DDB 后端 (开发机/训练/推理 统一一套, 仅 admin 管).
 * 2026-06-14 确定: 三类共用一套模板; 用户只能列 (选), 增删改仅 ws admin.
 *
 * 端点: /workspaces/{ws}/resource-templates
 *   GET    列 (统一一套, 全员可见)
 *   POST   建 (仅 ws admin)
 *   PUT    /{template_id}  改 (仅 ws admin)
 *   DELETE /{template_id}  删 (仅 ws admin)
 */
import { apiFetch } from '@/shared/api';
import i18n from '@/shared/i18n';

/** 三类统一字段 (dev/train/inference 共用, 单值 req=lim)。 */
export interface TemplateResource {
  gpu: number;
  cpu_cores: number;
  mem_gib: number;
  // EFA 网卡数 (多节点 GPU 训练 RDMA)。老模板无此字段, 读取时一律 `?? 0` 兜底。
  efa?: number;
}

export interface ResourceTemplateItem {
  template_id: string;
  name: string;
  description?: string | null;
  resource: TemplateResource;
  creator_username: string;
  created_at: string;
  updated_at: string;
}

/**
 * 资源规格人类可读串, 全站统一 (模板页「资源」列 + 三个创建页的模板 Select)。
 * 用全称 `N GPU · N 核 · N GiB · N EFA` 而非简写 `8G/96C/1152Gi` — 后者
 * 「8G」易被误读成 8G 内存。efa 老模板无此字段 → ?? 0 兜底。
 */
export function resourceText(r: TemplateResource): string {
  return i18n.t('resourceTemplate.specText', {
    ns: 'common',
    gpu: r.gpu,
    count: r.cpu_cores,
    mem: r.mem_gib,
    efa: r.efa ?? 0,
  });
}

/** 选资源最小的模板 (gpu→cpu→mem 排序), 供创建页默认选中最小配置。空数组返 undefined。 */
export function pickSmallestTemplate(
  list: ResourceTemplateItem[],
): ResourceTemplateItem | undefined {
  if (!list.length) return undefined;
  return [...list].sort((a, b) => {
    const ra = a.resource;
    const rb = b.resource;
    return (
      (ra.gpu ?? 0) - (rb.gpu ?? 0) ||
      (ra.cpu_cores ?? 0) - (rb.cpu_cores ?? 0) ||
      (ra.mem_gib ?? 0) - (rb.mem_gib ?? 0)
    );
  })[0];
}

export interface TemplateCreateBody {
  name: string;
  description?: string;
  resource: TemplateResource;
}

export interface TemplateUpdateBody {
  name?: string;
  description?: string;
  resource?: TemplateResource;
}

export function listResourceTemplates(
  wsId: string,
): Promise<ResourceTemplateItem[]> {
  return apiFetch<ResourceTemplateItem[]>(
    `/workspaces/${encodeURIComponent(wsId)}/resource-templates`,
  );
}

export function createResourceTemplate(
  wsId: string,
  body: TemplateCreateBody,
): Promise<ResourceTemplateItem> {
  return apiFetch<ResourceTemplateItem>(
    `/workspaces/${encodeURIComponent(wsId)}/resource-templates`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function updateResourceTemplate(
  wsId: string,
  templateId: string,
  body: TemplateUpdateBody,
): Promise<ResourceTemplateItem> {
  return apiFetch<ResourceTemplateItem>(
    `/workspaces/${encodeURIComponent(wsId)}/resource-templates/${encodeURIComponent(templateId)}`,
    { method: 'PUT', body: JSON.stringify(body) },
  );
}

export function deleteResourceTemplate(
  wsId: string,
  templateId: string,
): Promise<void> {
  return apiFetch<void>(
    `/workspaces/${encodeURIComponent(wsId)}/resource-templates/${encodeURIComponent(templateId)}`,
    { method: 'DELETE' },
  );
}
