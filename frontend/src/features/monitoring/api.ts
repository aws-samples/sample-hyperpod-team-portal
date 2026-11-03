/**
 * FSx CloudWatch 监控指标 API (所有登录用户可看, 与工作空间无关)。
 *
 * 后端契约 (app/modules/fsx_quota/api/monitoring_router.py):
 *   GET /monitoring/fsx/metrics?range=1h|6h|24h → { series: {util,free,tput,iops} }
 *
 * apiFetch 自动拼 /api/v1 前缀, 这里 path 不带前缀。
 */
import { apiFetch } from '@/shared/api';

/** 指标时序: {id: [[iso_ts, value], ...]} — id 为 util/free/tput/iops。 */
export type FsxMetricSeries = Record<string, [string, number][]>;

export type FsxMetricRange = '1h' | '6h' | '24h';

/** 可选 FSx (监控/配额下拉框): name (AWS Tags[Name]) 展示, filesystemId 值。 */
export interface FsxOption {
  filesystemId: string;
  name?: string | null;
  capacityGib?: number | null;
}

/** 下拉展示名: "<Name> (fs-id)"; 无 Name 时只显 fs-id。 */
export function fsxLabel(f: FsxOption): string {
  return f.name && f.name !== f.filesystemId
    ? `${f.name} (${f.filesystemId})`
    : f.filesystemId;
}

/** 列平台接入的 FSx (供下拉框选盘)。 */
export function listFsxFilesystems(): Promise<FsxOption[]> {
  return apiFetch<FsxOption[]>('/monitoring/fsx/filesystems');
}

export function getFsxMetrics(
  filesystemId: string,
  range: FsxMetricRange,
): Promise<FsxMetricSeries> {
  // query 参数走 FastAPI 原名 snake_case (Query 不做 camel 转换)。
  return apiFetch<{ series: FsxMetricSeries }>(
    `/monitoring/fsx/metrics?filesystem_id=${encodeURIComponent(filesystemId)}&range=${range}`,
  ).then((r) => r.series ?? {});
}
