import { mockWorkspaces } from './workspaces';

// ---------- Types (local to mock, not exported to global types per task brief) ----------

export type ModelSource = 'training' | 'huggingface' | 'upload';
export type ModelPrecision = 'bfloat16' | 'float16' | 'int8' | 'awq' | 'gptq' | 'fp8';

export interface ModelAsset {
  id: string;
  workspaceId: string;
  name: string;
  version: string;
  source: ModelSource;
  baseModel: string;
  sizeGb: number;
  precision: ModelPrecision;
  fsxPath: string;
  creator: string;
  createdAt: string;
  description?: string;
}

export type DatasetType = 'train' | 'validation' | 'test' | 'mixed';
export type DatasetSource = 's3' | 'huggingface' | 'upload';
export type DatasetVisibility = 'public' | 'workspace' | 'private';

export interface DatasetAsset {
  id: string;
  workspaceId: string;
  name: string;
  type: DatasetType;
  fsxPath: string;
  sizeGb: number;
  fileCount: number;
  version: string;
  source: DatasetSource;
  visibility: DatasetVisibility;
  updatedAt: string;
  description?: string;
}

export type ImageCategory = 'official' | 'team' | 'personal' | 'community';
export type ImageFramework = 'pytorch' | 'tensorflow' | 'vllm' | 'sglang' | 'trtllm';
export type ScanStatus = 'passed' | 'vulnerable' | 'unscanned';

export interface ImageAsset {
  id: string;
  workspaceId: string;
  category: ImageCategory;
  name: string;
  tag: string;
  framework: ImageFramework;
  cudaVersion: string;
  baseOs: string;
  sizeMb: number;
  scanStatus: ScanStatus;
  vulnerabilities: number;
  pushedAt: string;
  registry: string;
}

export type ResourcePoolType = 'general' | 'gpu-h100' | 'gpu-a100' | 'dedicated';
export type ResourcePoolStatus = 'available' | 'busy' | 'offline';

export interface ResourcePoolOption {
  id: string;
  name: string;
  displayName: string;
  poolType: ResourcePoolType;
  instanceType: string;
  nodeCount: number;
  availableNodes: number;
  totalGpu: number;
  usedGpu: number;
  queuedTasks: number;
  status: ResourcePoolStatus;
  description: string;
}

// ---------- Helpers ----------

const wsA = mockWorkspaces[0]?.id ?? 'ws-001';
const wsB = mockWorkspaces[1]?.id ?? 'ws-002';
const wsC = mockWorkspaces[2]?.id ?? 'ws-003';

const daysAgo = (d: number): string =>
  new Date(Date.now() - d * 86400_000).toISOString();

// ---------- Models (>=8) ----------

export const mockModels: ModelAsset[] = [
  {
    id: 'mdl-001',
    workspaceId: wsA,
    name: 'Qwen2.5-72B-FT-v1',
    version: 'v1',
    source: 'training',
    baseModel: 'Qwen/Qwen2.5-72B-Instruct',
    sizeGb: 144.8,
    precision: 'bfloat16',
    fsxPath: `/fsx/${wsA}/models/qwen2.5-72b-ft-v1`,
    creator: 'alice@example.com',
    createdAt: daysAgo(3),
    description: '基于 Qwen2.5-72B 对内部客服语料的 LoRA 合并权重',
  },
  {
    id: 'mdl-002',
    workspaceId: wsA,
    name: 'Qwen2.5-72B-FT-v2',
    version: 'v2',
    source: 'training',
    baseModel: 'Qwen/Qwen2.5-72B-Instruct',
    sizeGb: 144.8,
    precision: 'bfloat16',
    fsxPath: `/fsx/${wsA}/models/qwen2.5-72b-ft-v2`,
    creator: 'alice@example.com',
    createdAt: daysAgo(1),
    description: '在 v1 基础上扩充 30% 数据重训，eval 分数 +2.3',
  },
  {
    id: 'mdl-003',
    workspaceId: wsA,
    name: 'Llama-3.1-70B-Instruct',
    version: 'v1',
    source: 'huggingface',
    baseModel: 'meta-llama/Llama-3.1-70B-Instruct',
    sizeGb: 140.2,
    precision: 'bfloat16',
    fsxPath: `/fsx/${wsA}/models/llama-3.1-70b-instruct`,
    creator: 'bob@example.com',
    createdAt: daysAgo(10),
  },
  {
    id: 'mdl-004',
    workspaceId: wsA,
    name: 'Llama-3.1-70B-AWQ',
    version: 'v1',
    source: 'upload',
    baseModel: 'meta-llama/Llama-3.1-70B-Instruct',
    sizeGb: 39.6,
    precision: 'awq',
    fsxPath: `/fsx/${wsA}/models/llama-3.1-70b-awq`,
    creator: 'bob@example.com',
    createdAt: daysAgo(5),
    description: 'AWQ 4bit 量化，面向单卡 A100 推理',
  },
  {
    id: 'mdl-005',
    workspaceId: wsA,
    name: 'Mixtral-8x7B-FT',
    version: 'v1',
    source: 'training',
    baseModel: 'mistralai/Mixtral-8x7B-Instruct-v0.1',
    sizeGb: 93.4,
    precision: 'bfloat16',
    fsxPath: `/fsx/${wsA}/models/mixtral-8x7b-ft-v1`,
    creator: 'carol@example.com',
    createdAt: daysAgo(7),
  },
  {
    id: 'mdl-006',
    workspaceId: wsB,
    name: 'InternVL2-26B-CV',
    version: 'v1',
    source: 'training',
    baseModel: 'OpenGVLab/InternVL2-26B',
    sizeGb: 52.8,
    precision: 'bfloat16',
    fsxPath: `/fsx/${wsB}/models/internvl2-26b-cv-v1`,
    creator: 'david@example.com',
    createdAt: daysAgo(2),
    description: '视觉检测微调权重',
  },
  {
    id: 'mdl-007',
    workspaceId: wsB,
    name: 'DeepSeek-V2-Lite',
    version: 'v1',
    source: 'huggingface',
    baseModel: 'deepseek-ai/DeepSeek-V2-Lite',
    sizeGb: 31.2,
    precision: 'bfloat16',
    fsxPath: `/fsx/${wsB}/models/deepseek-v2-lite`,
    creator: 'eve@example.com',
    createdAt: daysAgo(15),
  },
  {
    id: 'mdl-008',
    workspaceId: wsC,
    name: 'RecSys-CTR-XGB',
    version: 'v3',
    source: 'training',
    baseModel: 'custom/xgboost-ctr',
    sizeGb: 1.8,
    precision: 'float16',
    fsxPath: `/fsx/${wsC}/models/recsys-ctr-xgb-v3`,
    creator: 'frank@example.com',
    createdAt: daysAgo(1),
    description: '推荐 CTR XGBoost 第三版',
  },
  {
    id: 'mdl-009',
    workspaceId: wsC,
    name: 'BGE-Reranker-Large',
    version: 'v1',
    source: 'huggingface',
    baseModel: 'BAAI/bge-reranker-large',
    sizeGb: 2.1,
    precision: 'float16',
    fsxPath: `/fsx/${wsC}/models/bge-reranker-large`,
    creator: 'grace@example.com',
    createdAt: daysAgo(20),
  },
];

// ---------- Datasets (>=8) ----------

export const mockDatasets: DatasetAsset[] = [
  {
    id: 'ds-001',
    workspaceId: wsA,
    name: 'customer-service-dialogs',
    type: 'train',
    fsxPath: `/fsx/${wsA}/datasets/cs-dialogs-v3`,
    sizeGb: 182.4,
    fileCount: 1248,
    version: 'v3',
    source: 's3',
    visibility: 'workspace',
    updatedAt: daysAgo(2),
    description: '客服对话训练集，已清洗脱敏',
  },
  {
    id: 'ds-002',
    workspaceId: wsA,
    name: 'cs-dialogs-val',
    type: 'validation',
    fsxPath: `/fsx/${wsA}/datasets/cs-dialogs-val`,
    sizeGb: 4.2,
    fileCount: 32,
    version: 'v1',
    source: 's3',
    visibility: 'workspace',
    updatedAt: daysAgo(2),
  },
  {
    id: 'ds-003',
    workspaceId: wsA,
    name: 'alpaca-gpt4-zh',
    type: 'train',
    fsxPath: `/fsx/${wsA}/datasets/alpaca-gpt4-zh`,
    sizeGb: 0.8,
    fileCount: 1,
    version: 'v1',
    source: 'huggingface',
    visibility: 'public',
    updatedAt: daysAgo(30),
  },
  {
    id: 'ds-004',
    workspaceId: wsA,
    name: 'internal-docs-rag',
    type: 'mixed',
    fsxPath: `/fsx/${wsA}/datasets/internal-docs-rag`,
    sizeGb: 56.3,
    fileCount: 18450,
    version: 'v2',
    source: 'upload',
    visibility: 'private',
    updatedAt: daysAgo(5),
    description: '内部文档 RAG 语料',
  },
  {
    id: 'ds-005',
    workspaceId: wsB,
    name: 'coco-2017',
    type: 'train',
    fsxPath: `/fsx/${wsB}/datasets/coco-2017`,
    sizeGb: 25.6,
    fileCount: 163957,
    version: 'v1',
    source: 's3',
    visibility: 'public',
    updatedAt: daysAgo(60),
  },
  {
    id: 'ds-006',
    workspaceId: wsB,
    name: 'detect-eval-custom',
    type: 'test',
    fsxPath: `/fsx/${wsB}/datasets/detect-eval-custom`,
    sizeGb: 3.4,
    fileCount: 2400,
    version: 'v2',
    source: 'upload',
    visibility: 'workspace',
    updatedAt: daysAgo(4),
  },
  {
    id: 'ds-007',
    workspaceId: wsC,
    name: 'criteo-clicks-1TB',
    type: 'train',
    fsxPath: `/fsx/${wsC}/datasets/criteo-clicks-1tb`,
    sizeGb: 1024,
    fileCount: 24,
    version: 'v1',
    source: 's3',
    visibility: 'workspace',
    updatedAt: daysAgo(14),
    description: 'Criteo 1TB 点击数据',
  },
  {
    id: 'ds-008',
    workspaceId: wsC,
    name: 'user-feature-store',
    type: 'mixed',
    fsxPath: `/fsx/${wsC}/datasets/user-feature-store-v5`,
    sizeGb: 72.1,
    fileCount: 512,
    version: 'v5',
    source: 'upload',
    visibility: 'private',
    updatedAt: daysAgo(1),
  },
  {
    id: 'ds-009',
    workspaceId: wsA,
    name: 'mmlu-zh-benchmark',
    type: 'test',
    fsxPath: `/fsx/shared/datasets/mmlu-zh-benchmark`,
    sizeGb: 0.12,
    fileCount: 57,
    version: 'v1',
    source: 'huggingface',
    visibility: 'public',
    updatedAt: daysAgo(90),
  },
];

// ---------- Images (>=20) ----------

const ECR_REGISTRY = '763104351884.dkr.ecr.us-west-2.amazonaws.com';

export const mockImages: ImageAsset[] = [
  // Official: 6 (AWS Deep Learning Containers)
  {
    id: 'img-001',
    workspaceId: 'global',
    category: 'official',
    name: 'pytorch-training',
    tag: '2.4.0-gpu-py311-cu124-ubuntu22.04-ec2',
    framework: 'pytorch',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 9624,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(6),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-002',
    workspaceId: 'global',
    category: 'official',
    name: 'pytorch-training',
    tag: '2.3.0-gpu-py310-cu121-ubuntu22.04-ec2',
    framework: 'pytorch',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 9312,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(45),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-003',
    workspaceId: 'global',
    category: 'official',
    name: 'pytorch-inference',
    tag: '2.4.0-gpu-py311-cu124-ubuntu22.04-ec2',
    framework: 'pytorch',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 7820,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(6),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-004',
    workspaceId: 'global',
    category: 'official',
    name: 'tensorflow-training',
    tag: '2.16.1-gpu-py311-cu124-ubuntu22.04-ec2',
    framework: 'tensorflow',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 8765,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(20),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-005',
    workspaceId: 'global',
    category: 'official',
    name: 'vllm',
    tag: '0.6.1-gpu-py311-cu124-ubuntu22.04-ec2',
    framework: 'vllm',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 10240,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(3),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-006',
    workspaceId: 'global',
    category: 'official',
    name: 'sglang',
    tag: '0.3.1-gpu-py310-cu121-ubuntu22.04-ec2',
    framework: 'sglang',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 9480,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(12),
    registry: ECR_REGISTRY,
  },

  // Team: 8 (distributed across workspaces so each ws sees a few)
  {
    id: 'img-101',
    workspaceId: wsA,
    category: 'team',
    name: 'team-a/pytorch-nlp',
    tag: '2.4-llama-efa',
    framework: 'pytorch',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 11200,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(2),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-102',
    workspaceId: wsA,
    category: 'team',
    name: 'team-a/vllm-serve',
    tag: '0.6.1-qwen-flashattn3',
    framework: 'vllm',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 10812,
    scanStatus: 'vulnerable',
    vulnerabilities: 2,
    pushedAt: daysAgo(4),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-103',
    workspaceId: wsA,
    category: 'team',
    name: 'team-a/deepspeed-zero3',
    tag: '0.14-pytorch-2.3',
    framework: 'pytorch',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 9856,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(18),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-104',
    workspaceId: wsA,
    category: 'team',
    name: 'team-a/trtllm-bench',
    tag: '0.12.0-cu124',
    framework: 'trtllm',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 12480,
    scanStatus: 'unscanned',
    vulnerabilities: 0,
    pushedAt: daysAgo(8),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-105',
    workspaceId: wsB,
    category: 'team',
    name: 'team-b/pytorch-cv',
    tag: '2.4-mmdetection',
    framework: 'pytorch',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 10300,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(5),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-106',
    workspaceId: wsB,
    category: 'team',
    name: 'team-b/yolo-detect',
    tag: 'v8-trt-cu124',
    framework: 'pytorch',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 8960,
    scanStatus: 'vulnerable',
    vulnerabilities: 5,
    pushedAt: daysAgo(22),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-107',
    workspaceId: wsC,
    category: 'team',
    name: 'team-c/recsys-xgb',
    tag: '2.0-feature-store',
    framework: 'tensorflow',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 6400,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(9),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-108',
    workspaceId: wsC,
    category: 'team',
    name: 'team-c/spark-etl',
    tag: '3.5-gpu-rapids-24.08',
    framework: 'pytorch',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 7200,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(11),
    registry: ECR_REGISTRY,
  },

  // Personal: 4
  {
    id: 'img-201',
    workspaceId: wsA,
    category: 'personal',
    name: 'alice/pytorch-dev',
    tag: 'nightly',
    framework: 'pytorch',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 10800,
    scanStatus: 'unscanned',
    vulnerabilities: 0,
    pushedAt: daysAgo(1),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-202',
    workspaceId: wsA,
    category: 'personal',
    name: 'alice/vllm-tinker',
    tag: '0.6-custom',
    framework: 'vllm',
    cudaVersion: '12.4',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 11024,
    scanStatus: 'unscanned',
    vulnerabilities: 0,
    pushedAt: daysAgo(0),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-203',
    workspaceId: wsB,
    category: 'personal',
    name: 'david/opencv-cu12',
    tag: '4.10-py311',
    framework: 'pytorch',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 7450,
    scanStatus: 'unscanned',
    vulnerabilities: 0,
    pushedAt: daysAgo(3),
    registry: ECR_REGISTRY,
  },
  {
    id: 'img-204',
    workspaceId: wsC,
    category: 'personal',
    name: 'frank/xgb-rapids',
    tag: '24.08-dev',
    framework: 'tensorflow',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 6100,
    scanStatus: 'unscanned',
    vulnerabilities: 0,
    pushedAt: daysAgo(2),
    registry: ECR_REGISTRY,
  },

  // Community: 2
  {
    id: 'img-301',
    workspaceId: 'global',
    category: 'community',
    name: 'huggingface/text-generation-inference',
    tag: '2.2.0',
    framework: 'pytorch',
    cudaVersion: '12.1',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 9800,
    scanStatus: 'passed',
    vulnerabilities: 0,
    pushedAt: daysAgo(25),
    registry: 'ghcr.io',
  },
  {
    id: 'img-302',
    workspaceId: 'global',
    category: 'community',
    name: 'nvcr.io/nvidia/pytorch',
    tag: '24.08-py3',
    framework: 'pytorch',
    cudaVersion: '12.6',
    baseOs: 'Ubuntu 22.04',
    sizeMb: 13500,
    scanStatus: 'vulnerable',
    vulnerabilities: 1,
    pushedAt: daysAgo(15),
    registry: 'nvcr.io',
  },
];

// ---------- Resource Pools (create form) ----------

export const mockResourcePoolOptions: ResourcePoolOption[] = [
  {
    id: 'pool-general',
    name: 'general-pool',
    displayName: '通用池',
    poolType: 'general',
    instanceType: 'g5.12xlarge (A10G x4)',
    nodeCount: 12,
    availableNodes: 9,
    totalGpu: 48,
    usedGpu: 12,
    queuedTasks: 2,
    status: 'available',
    description: '通用开发池，适合小规模调试与验证',
  },
  {
    id: 'pool-h100',
    name: 'gpu-h100-pool',
    displayName: 'GPU 加速池 — H100',
    poolType: 'gpu-h100',
    instanceType: 'p5.48xlarge (H100 x8)',
    nodeCount: 16,
    availableNodes: 12,
    totalGpu: 128,
    usedGpu: 32,
    queuedTasks: 1,
    status: 'available',
    description: '高带宽 EFA 互联，适合 70B+ 模型训练',
  },
  {
    id: 'pool-a100',
    name: 'gpu-a100-pool',
    displayName: 'GPU 加速池 — A100',
    poolType: 'gpu-a100',
    instanceType: 'p4de.24xlarge (A100 x8)',
    nodeCount: 8,
    availableNodes: 5,
    totalGpu: 64,
    usedGpu: 24,
    queuedTasks: 3,
    status: 'busy',
    description: '性价比最优，适合 13B~34B 训练 / 推理',
  },
  {
    id: 'pool-dedicated',
    name: 'team-a-dedicated',
    displayName: '专属池 — Team A',
    poolType: 'dedicated',
    instanceType: 'p5.48xlarge (H100 x8)',
    nodeCount: 4,
    availableNodes: 3,
    totalGpu: 32,
    usedGpu: 8,
    queuedTasks: 0,
    status: 'available',
    description: 'Team A NLP 专属预留池，需要 admin 授权',
  },
];
