/**
 * Workspace API — wraps /workspaces CRUD + members.
 *
 * Wave 3 (C3) migration: moved from `src/api/workspace.ts`.
 */
import { apiFetch } from '@/shared/api';
import type { IdcUserSummary } from '@/api/user';

export type WorkspaceStatus = 'active' | 'suspended' | 'deleting' | string;
export type WorkspaceRole = 'admin' | 'member';

export interface Workspace {
  id: string;
  cluster_id: string;
  cluster_tag: string;
  name: string;
  display_name: string;
  namespace: string;
  description: string | null;
  owner_user_id: string;
  owner_display_name: string;
  status: WorkspaceStatus;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceDetail extends Workspace {
  quota_summary: Record<string, number> | null;
  metadata_json: Record<string, unknown>;
}

export interface WorkspaceMember {
  user_id: string;
  email: string;
  display_name: string;
  role: WorkspaceRole;
  joined_at: string;
}

/** AWS ComputeQuotaResource 初始资源 (可选). */
export interface WorkspaceQuotaResourceRequest {
  instance_type: string;
  count?: number;
  accelerators?: number;
  v_cpu?: number;
  memory_in_gi_b?: number;
}

export type WorkspaceSharingStrategy = 'LendAndBorrow' | 'Lend' | 'DontLend';
export type WorkspacePreemptPolicy = 'LowerPriority' | 'Never';

export interface WorkspaceCreatePayload {
  cluster_id: string;
  /** AWS Team Name · 小写+连字符 · 最长 40 字符 */
  name: string;
  display_name: string;
  description?: string;
  /** 可不传 · 后端会强制加 `hyperpod-ns-` 前缀对齐 AWS */
  namespace?: string;
  // ===== AWS ComputeQuota 初始字段 (均可选 · 后端有默认值) =====
  /** 0-100 · 同集群 team 之间抢空闲资源的权重 · 默认 10 */
  fair_share_weight?: number;
  /** 默认 LendAndBorrow */
  sharing_strategy?: WorkspaceSharingStrategy;
  /** 默认 LowerPriority */
  preempt_team_tasks?: WorkspacePreemptPolicy;
  /** 默认 [] · 建空配额 · 后续走 /quota PATCH 加资源 */
  resources?: WorkspaceQuotaResourceRequest[];
}

export interface WorkspaceUpdatePayload {
  display_name?: string;
  description?: string;
}

export interface ListWorkspacesParams {
  cluster_id?: string;
  q?: string;
  // 注意: 不再有 user_id 参数。可见范围由后端按已认证身份强制过滤
  // (超管→全部, 普通用户→自己 owner+member)。前端无法、也不应自决可见性
  // (越权修复 2026-06-14)。
}

function buildQuery(params?: Record<string, string | undefined>): string {
  if (!params) return '';
  const pairs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `?${pairs.join('&')}` : '';
}

export function listWorkspaces(params?: ListWorkspacesParams): Promise<Workspace[]> {
  const qs = buildQuery(
    params
      ? {
          cluster_id: params.cluster_id,
          q: params.q,
        }
      : undefined,
  );
  return apiFetch<Workspace[]>(`/workspaces${qs}`);
}

export function getWorkspace(id: string): Promise<WorkspaceDetail> {
  return apiFetch<WorkspaceDetail>(`/workspaces/${encodeURIComponent(id)}`);
}

export function createWorkspace(payload: WorkspaceCreatePayload): Promise<WorkspaceDetail> {
  return apiFetch<WorkspaceDetail>('/workspaces', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateWorkspace(
  id: string,
  payload: WorkspaceUpdatePayload,
): Promise<WorkspaceDetail> {
  return apiFetch<WorkspaceDetail>(`/workspaces/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteWorkspace(id: string): Promise<void> {
  return apiFetch<void>(`/workspaces/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function listMembers(wsId: string): Promise<WorkspaceMember[]> {
  return apiFetch<WorkspaceMember[]>(`/workspaces/${encodeURIComponent(wsId)}/members`);
}

// ===== Members 写操作 =====

export interface AddMemberPayload {
  user_id: string; // = IdC username
  role: WorkspaceRole;
}

export function addMember(wsId: string, payload: AddMemberPayload): Promise<WorkspaceMember> {
  return apiFetch<WorkspaceMember>(
    `/workspaces/${encodeURIComponent(wsId)}/members`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function updateMemberRole(
  wsId: string,
  userId: string,
  role: WorkspaceRole,
): Promise<WorkspaceMember> {
  return apiFetch<WorkspaceMember>(
    `/workspaces/${encodeURIComponent(wsId)}/members/${encodeURIComponent(userId)}`,
    { method: 'PUT', body: JSON.stringify({ role }) },
  );
}

export function removeMember(wsId: string, userId: string): Promise<void> {
  return apiFetch<void>(
    `/workspaces/${encodeURIComponent(wsId)}/members/${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );
}

/** ws 管理员加成员搜 IdC 用户 (ws 级鉴权; 平台超管的 /idc/users 仍可用)。 */
export function searchWsIdcUsers(
  wsId: string,
  q: string,
): Promise<IdcUserSummary[]> {
  return apiFetch<IdcUserSummary[]>(
    `/workspaces/${encodeURIComponent(wsId)}/idc/users?q=${encodeURIComponent(q)}`,
  );
}

// ===== FSx 候选池 + ws 内 FSx 挂载 =====

export interface FsxFilesystemSummary {
  filesystem_id: string;
  name: string;
  dns_name: string;
  mount_name: string;
  capacity_gib: number;
  deployment_type: string | null;
  subnet_id: string | null;
  lifecycle: string;
}

export function listFsxCandidates(): Promise<FsxFilesystemSummary[]> {
  return apiFetch<FsxFilesystemSummary[]>('/fsx-filesystems');
}

export interface FsxDirectory {
  name: string;
  gid: number;
}

export function listFsxDirectories(
  filesystemId: string,
  path = '',
): Promise<FsxDirectory[]> {
  // path: 相对 /fsx 的子目录 (空=根), 级联列下一层用
  const qs = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiFetch<FsxDirectory[]>(
    `/fsx-filesystems/${encodeURIComponent(filesystemId)}/directories${qs}`,
  );
}

/** ws 管理员挂载表单: 列候选 FSx 文件系统 (ws 级鉴权)。 */
export function listWsFsxCandidates(wsId: string): Promise<FsxFilesystemSummary[]> {
  return apiFetch<FsxFilesystemSummary[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx/candidate-filesystems`,
  );
}

/** ws 管理员挂载表单: 列 gid==primary_gid 的可挂目录 (primary_gid 空则空)。 */
export function listWsMountableDirs(
  wsId: string,
  filesystemId: string,
  path = '',
): Promise<FsxDirectory[]> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiFetch<FsxDirectory[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx/candidate-filesystems/${encodeURIComponent(filesystemId)}/mountable-dirs${qs}`,
  );
}

export interface FsxFile {
  name: string;
}

export function listFsxFiles(
  filesystemId: string,
  path = '',
): Promise<FsxFile[]> {
  // 列 /fsx[/<path>] 下普通文件 (训练任务启动文件下拉用)
  const qs = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiFetch<FsxFile[]>(
    `/fsx-filesystems/${encodeURIComponent(filesystemId)}/files${qs}`,
  );
}

export interface WorkspaceFsxMount {
  /** 用户填的别名, FSx 维度 ws 内唯一. PVC 名 = pvc-ws-fsx-{mount_id}-{rw|ro} */
  mount_id: string;
  /** 一句话说明, 仅展示用 */
  description: string;
  filesystem_id: string;
  mount_path: string;
  pv_name: string | null;
  /** 兼容旧字段 = pvc_name_rw */
  pvc_name: string | null;
  pvc_name_rw: string | null;
  pvc_name_ro: string | null;
  attached_at: string;
  /** /fsx/<subdir>; 旧 mount 记录可能为 null */
  subdir: string | null;
  /** subdir 对应 POSIX gid (后端探测得到); 旧 mount 记录可能为 null */
  gid: number | null;
  name: string | null;
  capacity_gib: number | null;
  dns_name: string | null;
  /** FSx 原始 lustre mountname (如 jjnz5b4v) */
  mount_name: string | null;
  /** mount_name 拼 subdir (如 jjnz5b4v/team-a) = operator/PV 挂载名, 推理隔离用 */
  full_mount_name: string | null;
}

export function listWorkspaceFsx(wsId: string): Promise<WorkspaceFsxMount[]> {
  return apiFetch<WorkspaceFsxMount[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx`,
  );
}

export interface AttachFsxPayload {
  /** 必填, ^[a-z][a-z0-9-]{2,39}$, ws 内 FSx 维度唯一 */
  mount_id: string;
  /** 可选, ≤ 200 字符, 支持中文 */
  description?: string;
  filesystem_id: string;
  /** /fsx/<subdir>, 支持多级子路径如 team-a/train/proj-b. gid 由后端探测, 不传 */
  subdir: string;
  /** Pod 内挂载路径, / 开头 */
  mount_path: string;
}

export function attachFsx(
  wsId: string,
  payload: AttachFsxPayload,
): Promise<WorkspaceFsxMount[]> {
  return apiFetch<WorkspaceFsxMount[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function detachFsx(
  wsId: string,
  mountId: string,
  force: boolean = false,
): Promise<WorkspaceFsxMount[]> {
  const qs = force ? '?force=true' : '';
  return apiFetch<WorkspaceFsxMount[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx/${encodeURIComponent(mountId)}${qs}`,
    { method: 'DELETE' },
  );
}

// ===== FSx 挂载成员级授权 (grants) =====

export type MountAccess = 'ro' | 'rw';

export interface MountGrant {
  username: string;
  access: MountAccess;
  mount_id: string;
  granted_by: string;
  granted_at: string;
}

export function listMountGrants(
  wsId: string,
  mountId: string,
): Promise<MountGrant[]> {
  return apiFetch<MountGrant[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx/${encodeURIComponent(mountId)}/grants`,
  );
}

export function grantMount(
  wsId: string,
  mountId: string,
  username: string,
  access: MountAccess,
): Promise<MountGrant[]> {
  return apiFetch<MountGrant[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx/${encodeURIComponent(mountId)}/grants`,
    { method: 'POST', body: JSON.stringify({ username, access }) },
  );
}

export function revokeMount(
  wsId: string,
  mountId: string,
  username: string,
): Promise<MountGrant[]> {
  return apiFetch<MountGrant[]>(
    `/workspaces/${encodeURIComponent(wsId)}/fsx/${encodeURIComponent(mountId)}/grants/${encodeURIComponent(username)}`,
    { method: 'DELETE' },
  );
}

// ===== S3 候选池 + ws 内 S3 挂载 =====

export interface S3BucketSummary {
  bucket_name: string;
  name: string;
  region: string;
}

/**
 * 平台级: 列所有受管 S3 bucket (require_admin · 仅平台超管)。
 * ws 管理员的挂载表单请勿用此接口 (会 403), 应走 listWsS3BucketCandidates。
 */
export function listS3BucketCandidates(): Promise<S3BucketSummary[]> {
  return apiFetch<S3BucketSummary[]>('/s3-buckets');
}

/** ws 管理员挂载表单: 列候选 S3 bucket (ws 级鉴权)。 */
export function listWsS3BucketCandidates(wsId: string): Promise<S3BucketSummary[]> {
  return apiFetch<S3BucketSummary[]>(
    `/workspaces/${encodeURIComponent(wsId)}/s3/candidate-buckets`,
  );
}

export interface WorkspaceS3Mount {
  /** 用户填的别名, S3 维度 ws 内唯一. PVC 名 = pvc-ws-s3-{mount_id} */
  mount_id: string;
  /** 一句话说明, 仅展示用 */
  description: string;
  bucket_name: string;
  prefix: string;
  mount_path: string;
  region: string;
  pv_name: string;
  pvc_name: string;
  attached_at: string;
}

export function listWorkspaceS3(wsId: string): Promise<WorkspaceS3Mount[]> {
  return apiFetch<WorkspaceS3Mount[]>(
    `/workspaces/${encodeURIComponent(wsId)}/s3`,
  );
}

export interface AttachS3Payload {
  /** 必填, ^[a-z][a-z0-9-]{2,39}$, ws 内 S3 维度唯一 */
  mount_id: string;
  /** 可选, ≤ 200 字符, 支持中文 */
  description?: string;
  bucket_name: string;
  mount_path: string;
  prefix?: string;
}

export function attachS3(
  wsId: string,
  payload: AttachS3Payload,
): Promise<WorkspaceS3Mount[]> {
  return apiFetch<WorkspaceS3Mount[]>(
    `/workspaces/${encodeURIComponent(wsId)}/s3`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function detachS3(
  wsId: string,
  mountId: string,
  force: boolean = false,
): Promise<WorkspaceS3Mount[]> {
  const qs = force ? '?force=true' : '';
  return apiFetch<WorkspaceS3Mount[]>(
    `/workspaces/${encodeURIComponent(wsId)}/s3/${encodeURIComponent(mountId)}${qs}`,
    { method: 'DELETE' },
  );
}
