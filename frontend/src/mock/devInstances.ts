import type { DevInstance, GpuType, JobStatus } from '@/types';
import { mockWorkspaces } from './workspaces';
import { mockUsers } from './users';

const GPU_POOL: GpuType[] = ['A100', 'H100', 'g5.8xlarge', 'g5.12xlarge'];
const STATUS_POOL: JobStatus[] = ['running', 'pending', 'stopped', 'failed', 'running'];
const IMAGE_POOL = [
  'pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime',
  'nvcr.io/nvidia/pytorch:24.05-py3',
  'huggingface/transformers-pytorch-gpu:latest',
];

const pick = <T,>(arr: T[], idx: number): T => arr[idx % arr.length] as T;

const instances: DevInstance[] = [];
mockWorkspaces.forEach((ws, wsIdx) => {
  for (let i = 0; i < 5; i += 1) {
    const seed = wsIdx * 100 + i;
    instances.push({
      id: `dev-${ws.id}-${String(i + 1).padStart(3, '0')}`,
      workspaceId: ws.id,
      name: `${ws.name}-dev-${i + 1}`,
      status: pick(STATUS_POOL, seed),
      gpuType: pick(GPU_POOL, seed),
      gpuCount: (seed % 4) + 1,
      creator: pick(mockUsers, seed).email,
      createdAt: new Date(Date.now() - seed * 3600_000).toISOString(),
      image: pick(IMAGE_POOL, seed),
      fsxMounts: ['/fsx/shared', `/fsx/${ws.name}`],
      sshReady: seed % 3 !== 0,
    });
  }
});

export const mockDevInstances: DevInstance[] = instances;
