/**
 * Registry 只读 API · ECR 镜像 dropdown 数据源.
 *
 * 后端: app/modules/registry/api/router.py
 */

import { apiFetch } from '@/shared/api';

export interface EcrRepo {
  name: string;
  uri: string;
  registry_id: string;
}

export interface EcrTag {
  tag: string;
  digest: string;
  pushed_at_iso: string | null;
  size_mb: number;
}

export const listEcrRepos = (): Promise<EcrRepo[]> =>
  apiFetch('/registry/ecr/repos');

export const listEcrTags = (repoName: string): Promise<EcrTag[]> =>
  apiFetch(`/registry/ecr/repos/${encodeURIComponent(repoName)}/tags`);

// ---------- 镜像中心: 工作空间镜像注册 (引用模型, 落 DDB) ----------

export type ImageUse = 'dev' | 'training' | 'inference';

export interface WorkspaceImage {
  id: string;
  image_uri: string;
  display_name: string;
  uses: ImageUse[];
  source: 'ecr-private' | 'ecr-public';
  creator_username: string;
  created_at: string;
}

export interface RegisterImageBody {
  image_uri: string;
  display_name?: string;
  uses: ImageUse[];
  source?: 'ecr-private' | 'ecr-public';
}

export const listWorkspaceImages = (wsId: string): Promise<WorkspaceImage[]> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/images`);

export const registerWorkspaceImage = (
  wsId: string,
  body: RegisterImageBody,
): Promise<WorkspaceImage> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/images`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const unregisterWorkspaceImage = (
  wsId: string,
  imageId: string,
): Promise<void> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/images/${encodeURIComponent(imageId)}`, {
    method: 'DELETE',
  });

// ---------- 镜像在线构建 (Dockerfile → CodeBuild → 自动注册) ----------

export type BuildStatus = 'building' | 'success' | 'failed';
export type BuildComputeType =
  | 'BUILD_GENERAL1_SMALL'
  | 'BUILD_GENERAL1_MEDIUM'
  | 'BUILD_GENERAL1_LARGE'
  | 'BUILD_GENERAL1_2XLARGE';

export interface ImageBuild {
  id: string;
  status: BuildStatus;
  target_tag: string;
  target_uri: string;
  uses: ImageUse[];
  compute_type: string;
  timeout_minutes: number;
  dockerfile: string;
  logs_url: string;
  codebuild_id: string;
  creator_username: string;
  created_at: string;
  updated_at: string;
}

export interface SubmitBuildBody {
  dockerfile: string;
  target_tag: string;
  uses: ImageUse[];
  compute_type: BuildComputeType;
  timeout_minutes?: number;
}

export const submitImageBuild = (
  wsId: string,
  body: SubmitBuildBody,
): Promise<ImageBuild> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/image-builds`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const listImageBuilds = (wsId: string): Promise<ImageBuild[]> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/image-builds`);

export const getImageBuild = (wsId: string, id: string): Promise<ImageBuild> =>
  apiFetch(`/workspaces/${encodeURIComponent(wsId)}/image-builds/${encodeURIComponent(id)}`);

export const getImageBuildLogs = (
  wsId: string,
  id: string,
  nextToken?: string,
): Promise<{
  log_text: string;
  log_group: string;
  region: string;
  logs_url: string;
  next_token: string;
}> => {
  const base = `/workspaces/${encodeURIComponent(wsId)}/image-builds/${encodeURIComponent(id)}/logs`;
  const q = nextToken ? `?next_token=${encodeURIComponent(nextToken)}` : '';
  return apiFetch(`${base}${q}`);
};
