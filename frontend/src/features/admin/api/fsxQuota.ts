/**
 * FSx 一级目录配额 + CloudWatch 指标 API 封装 (平台超管)。
 *
 * 后端契约 (app/modules/fsx_quota/api/router.py):
 *   GET   /admin/fsx-quota/directories        → {totalGib, directories: DirQuota[]}
 *   POST  /admin/fsx-quota/directories        body {name, hardGib} → DirQuota
 *   PATCH /admin/fsx-quota/directories/{name}  body {hardGib}       → DirQuota
 *
 * 监控指标已拆到 @/features/monitoring/api (所有用户可看)。
 * 编码: 后端 Pydantic alias_generator=to_camel + populate_by_name, 请求/响应均 camelCase。
 * 注意: shared/api 的 apiFetch 会自动拼 `/api/v1` 前缀, 这里 path 不带前缀; body 需手动 stringify。
 */
import { apiFetch } from '@/shared/api';

export interface DirQuota {
  name: string;
  gid: number;
  pid: number;
  usedGib: number;
  softGib: number;
  hardGib: number;
  pct: number;
}

export interface DirQuotaList {
  // FS 真实总容量 (StorageCapacity); 拿不到时 null
  totalGib: number | null;
  directories: DirQuota[];
}

export function listFsxDirectories(filesystemId: string): Promise<DirQuotaList> {
  // query 参数走 FastAPI 原名 snake_case (Query 不做 camel 转换; body 才 camel)。
  return apiFetch<DirQuotaList>(
    `/admin/fsx-quota/directories?filesystem_id=${encodeURIComponent(filesystemId)}`,
  );
}

export function createFsxDirectory(
  filesystemId: string,
  name: string,
  hardGib: number,
  gid?: number,
): Promise<DirQuota> {
  const body: Record<string, unknown> = { filesystemId, name, hardGib };
  // gid 仅在选择复用已有 team 时带上; 不传则后端自动新分配。
  if (gid != null) body.gid = gid;
  return apiFetch<DirQuota>('/admin/fsx-quota/directories', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function updateFsxQuota(
  filesystemId: string,
  name: string,
  hardGib: number,
): Promise<DirQuota> {
  return apiFetch<DirQuota>(`/admin/fsx-quota/directories/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify({ filesystemId, hardGib }),
  });
}
