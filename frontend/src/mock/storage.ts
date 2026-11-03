/**
 * Storage & permission mocks for the combined "/admin/storage" page (M1).
 *
 * Three layers align with the design doc:
 *   L1 FsxFileSystem     · physical FSx Lustre instances
 *   L2 FsxPermissionGroup · per-workspace sub-path containers with POSIX uid/gid + quota
 *   L3 FsxPathGrant       · path-level ro/rw grants to user|role, with optional
 *                           dataset_name that promotes the grant into a dataset alias.
 *
 * All identifiers are intentionally stable so redirects carrying query params
 * (e.g. ?tab=permission-groups&pg=pg-1) keep working across reloads.
 */

/* ============================================================================
 * L1 · File system
 * ========================================================================== */

export type FsxDeploymentType = 'SCRATCH_2' | 'PERSISTENT_2';
export type FsxState = 'Available' | 'Creating' | 'Failed' | 'Deleting';

export interface MockFsxFileSystem {
  id: string;
  fsx_id: string;
  display_name: string;
  lustre_version: string;
  storage_capacity_gb: number;
  used_gb: number;
  deployment_type: FsxDeploymentType;
  state: FsxState;
  throughput_mbps_per_tb: number;
  mount_dns: string;
  mount_name: string;
  vpc_id: string;
  subnet_id: string;
  created_at: string;
}

export const MOCK_FILE_SYSTEMS: MockFsxFileSystem[] = [
  {
    id: 'fs-uuid-1',
    fsx_id: 'fs-0abc123456789',
    display_name: 'team-main',
    lustre_version: '2.15',
    storage_capacity_gb: 1200,
    used_gb: 820,
    deployment_type: 'SCRATCH_2',
    state: 'Available',
    throughput_mbps_per_tb: 250,
    mount_dns: 'fs-0abc123456789.fsx.us-west-2.amazonaws.com',
    mount_name: 'mrxb1bmv',
    vpc_id: 'vpc-0a1b2c3d',
    subnet_id: 'subnet-0a1b2c3d',
    created_at: '2026-04-12T02:15:00Z',
  },
  {
    id: 'fs-uuid-2',
    fsx_id: 'fs-0def456789abc',
    display_name: 'shared-pretrained',
    lustre_version: '2.15',
    storage_capacity_gb: 4800,
    used_gb: 3100,
    deployment_type: 'PERSISTENT_2',
    state: 'Available',
    throughput_mbps_per_tb: 125,
    mount_dns: 'fs-0def456789abc.fsx.us-west-2.amazonaws.com',
    mount_name: 'k9pqz2ab',
    vpc_id: 'vpc-0a1b2c3d',
    subnet_id: 'subnet-0a1b2c3e',
    created_at: '2026-03-08T07:40:00Z',
  },
];

/* ============================================================================
 * L2 · Permission group
 * ========================================================================== */

export interface MockPermissionGroup {
  id: string;
  file_system_id: string;
  file_system_display_name: string;
  /** NULL means global — shared across all workspaces. */
  workspace_id: string | null;
  workspace_name: string | null;
  workspace_display_name: string | null;
  name: string;
  description?: string;
  subpath_root: string;
  posix_uid: number;
  posix_gid: number;
  quota_gb: number;
  used_gb: number;
  state: 'Available' | 'Provisioning' | 'Failed';
}

export const MOCK_PERMISSION_GROUPS: MockPermissionGroup[] = [
  {
    id: 'pg-1',
    file_system_id: 'fs-uuid-1',
    file_system_display_name: 'team-main',
    workspace_id: 'ws-001',
    workspace_name: 'team-a-nlp',
    workspace_display_name: 'Team A — NLP',
    name: 'team-a-datasets',
    description: 'Team A 数据集池 · 公共挂载',
    subpath_root: '/team-a/datasets',
    posix_uid: 10001,
    posix_gid: 20001,
    quota_gb: 1000,
    used_gb: 600,
    state: 'Available',
  },
  {
    id: 'pg-2',
    file_system_id: 'fs-uuid-1',
    file_system_display_name: 'team-main',
    workspace_id: 'ws-001',
    workspace_name: 'team-a-nlp',
    workspace_display_name: 'Team A — NLP',
    name: 'team-a-checkpoints',
    description: 'Team A 训练 checkpoint 输出路径',
    subpath_root: '/team-a/checkpoints',
    posix_uid: 10001,
    posix_gid: 20002,
    quota_gb: 500,
    used_gb: 200,
    state: 'Available',
  },
  {
    id: 'pg-3',
    file_system_id: 'fs-uuid-1',
    file_system_display_name: 'team-main',
    workspace_id: 'ws-002',
    workspace_name: 'team-b-cv',
    workspace_display_name: 'Team B — Computer Vision',
    name: 'team-b-models',
    description: 'Team B 模型发布 + 训练产出',
    subpath_root: '/team-b/models',
    posix_uid: 10002,
    posix_gid: 20003,
    quota_gb: 800,
    used_gb: 450,
    state: 'Available',
  },
  {
    id: 'pg-4',
    file_system_id: 'fs-uuid-2',
    file_system_display_name: 'shared-pretrained',
    workspace_id: null,
    workspace_name: null,
    workspace_display_name: null,
    name: 'shared-pretrained-models',
    description: '全局共享 · 预训练基础模型权重',
    subpath_root: '/shared/pretrained',
    posix_uid: 10000,
    posix_gid: 20000,
    quota_gb: 4000,
    used_gb: 3000,
    state: 'Available',
  },
  {
    id: 'pg-5',
    file_system_id: 'fs-uuid-2',
    file_system_display_name: 'shared-pretrained',
    workspace_id: null,
    workspace_name: null,
    workspace_display_name: null,
    name: 'shared-public-datasets',
    description: '全局共享 · 公共数据集镜像',
    subpath_root: '/shared/datasets',
    posix_uid: 10000,
    posix_gid: 20000,
    quota_gb: 800,
    used_gb: 100,
    state: 'Available',
  },
];

/* ============================================================================
 * L3 · Path grant (a dataset is a grant with `dataset_name != null`)
 * ========================================================================== */

export type GrantMode = 'ro' | 'rw';
export type WorkspaceRole = 'owner' | 'admin' | 'developer' | 'viewer';

export interface MockPathGrant {
  id: string;
  permission_group_id: string;
  path: string;
  mode: GrantMode;
  /** Either user_id (specific user) or workspace_role (role-based) is populated. */
  user_id: string | null;
  user_display_name: string | null;
  workspace_role: WorkspaceRole | null;
  /** Promotes this grant into a dataset alias when set. */
  dataset_name: string | null;
  dataset_description: string | null;
  readme_url: string | null;
  granted_by_id: string;
  granted_by_display_name: string;
  granted_at: string;
  /** Display-only sizing — in real M2 this comes from `du -sh` or FSx API. */
  size_gb: number;
  file_count: number;
}

export const MOCK_PATH_GRANTS: MockPathGrant[] = [
  {
    id: 'g1',
    permission_group_id: 'pg-1',
    path: '/team-a/datasets/imagenet',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'developer',
    dataset_name: 'imagenet-1k',
    dataset_description: 'ImageNet 1K 标准图像分类数据集 · 约 1.28M 张图 · 1000 类',
    readme_url: 's3://datasets-team-a/imagenet/README.md',
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-05-01T10:00:00Z',
    size_gb: 150,
    file_count: 1281167,
  },
  {
    id: 'g2',
    permission_group_id: 'pg-1',
    path: '/team-a/datasets/coco',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'developer',
    dataset_name: 'coco-2017',
    dataset_description: 'COCO 2017 目标检测 / 分割 · 标注完备',
    readme_url: 's3://datasets-team-a/coco/README.md',
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-05-02T03:12:00Z',
    size_gb: 25,
    file_count: 163957,
  },
  {
    id: 'g3',
    permission_group_id: 'pg-1',
    path: '/team-a/datasets/internal-corpus',
    mode: 'rw',
    user_id: 'u-002',
    user_display_name: 'Bob Wang',
    workspace_role: null,
    dataset_name: null,
    dataset_description: null,
    readme_url: null,
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-05-05T09:20:00Z',
    size_gb: 72,
    file_count: 32415,
  },
  {
    id: 'g4',
    permission_group_id: 'pg-2',
    path: '/team-a/checkpoints/llama-finetune',
    mode: 'rw',
    user_id: null,
    user_display_name: null,
    workspace_role: 'developer',
    dataset_name: null,
    dataset_description: null,
    readme_url: null,
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-05-03T14:00:00Z',
    size_gb: 180,
    file_count: 42,
  },
  {
    id: 'g5',
    permission_group_id: 'pg-3',
    path: '/team-b/models/release',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'viewer',
    dataset_name: null,
    dataset_description: null,
    readme_url: null,
    granted_by_id: 'u-003',
    granted_by_display_name: 'Carol Li',
    granted_at: '2026-04-20T02:00:00Z',
    size_gb: 90,
    file_count: 256,
  },
  {
    id: 'g6',
    permission_group_id: 'pg-3',
    path: '/team-b/models/staging',
    mode: 'rw',
    user_id: null,
    user_display_name: null,
    workspace_role: 'owner',
    dataset_name: null,
    dataset_description: null,
    readme_url: null,
    granted_by_id: 'u-003',
    granted_by_display_name: 'Carol Li',
    granted_at: '2026-04-21T06:30:00Z',
    size_gb: 40,
    file_count: 88,
  },
  {
    id: 'g7',
    permission_group_id: 'pg-4',
    path: '/shared/pretrained/llama-3-8b',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'developer',
    dataset_name: 'llama-3-8b-weights',
    dataset_description: 'Llama 3 8B 基础模型权重 · HuggingFace 版本 · FP16',
    readme_url: 's3://model-hub/llama-3-8b/README.md',
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-04-10T01:00:00Z',
    size_gb: 16,
    file_count: 47,
  },
  {
    id: 'g8',
    permission_group_id: 'pg-4',
    path: '/shared/pretrained/qwen-2-7b',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'developer',
    dataset_name: 'qwen-2-7b-weights',
    dataset_description: 'Qwen 2 7B 基础模型权重 · safetensors 格式',
    readme_url: 's3://model-hub/qwen-2-7b/README.md',
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-04-12T05:00:00Z',
    size_gb: 14,
    file_count: 38,
  },
  {
    id: 'g9',
    permission_group_id: 'pg-5',
    path: '/shared/datasets/wikipedia-2024',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'developer',
    dataset_name: 'wikipedia-2024',
    dataset_description: 'Wikipedia 2024 快照 · 多语言 · 已去 markup',
    readme_url: 's3://datasets-public/wikipedia-2024/README.md',
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-04-15T11:00:00Z',
    size_gb: 55,
    file_count: 295,
  },
  {
    id: 'g10',
    permission_group_id: 'pg-5',
    path: '/shared/datasets/common-crawl-sample',
    mode: 'ro',
    user_id: null,
    user_display_name: null,
    workspace_role: 'viewer',
    dataset_name: null,
    dataset_description: null,
    readme_url: null,
    granted_by_id: 'u-001',
    granted_by_display_name: 'Alice Chen',
    granted_at: '2026-04-16T06:00:00Z',
    size_gb: 45,
    file_count: 120,
  },
];
