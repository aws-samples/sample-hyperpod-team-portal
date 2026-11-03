import type { Framework, GpuType, JobStatus, TrainingJob } from '@/types';
import { mockWorkspaces } from './workspaces';
import { mockUsers } from './users';

const GPU_POOL: GpuType[] = ['A100', 'H100', 'p5.48xlarge', 'g5.12xlarge'];
const STATUS_POOL: JobStatus[] = [
  'running',
  'succeeded',
  'failed',
  'queued',
  'pending',
  'stopped',
  'running',
];
const FRAMEWORK_POOL: Framework[] = ['pytorch', 'tensorflow'];
const IMAGE_POOL = [
  'nvcr.io/nvidia/pytorch:24.05-py3',
  'pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime',
  'tensorflow/tensorflow:2.15.0-gpu',
];

const pick = <T,>(arr: T[], idx: number): T => arr[idx % arr.length] as T;

const jobs: TrainingJob[] = [];
mockWorkspaces.forEach((ws, wsIdx) => {
  for (let i = 0; i < 15; i += 1) {
    const seed = wsIdx * 100 + i;
    const status = pick(STATUS_POOL, seed);
    const createdAt = new Date(Date.now() - seed * 7200_000).toISOString();
    const startedAt =
      status === 'pending' || status === 'queued'
        ? undefined
        : new Date(Date.now() - seed * 7200_000 + 600_000).toISOString();
    const endedAt =
      status === 'succeeded' || status === 'failed' || status === 'stopped'
        ? new Date(Date.now() - seed * 3600_000).toISOString()
        : undefined;
    const totalSteps = 10_000;
    const currentStep =
      status === 'running' ? 2000 + (seed * 137) % 7000 : totalSteps;
    jobs.push({
      id: `tj-${ws.id}-${String(i + 1).padStart(3, '0')}`,
      workspaceId: ws.id,
      experimentId: i % 3 === 0 ? `exp-${ws.id}-${(i % 5) + 1}` : undefined,
      name: `${ws.name}-train-${i + 1}`,
      status,
      gpuType: pick(GPU_POOL, seed),
      gpuCount: ((seed % 4) + 1) * 2,
      nodeCount: (seed % 4) + 1,
      creator: pick(mockUsers, seed).email,
      createdAt,
      startedAt,
      endedAt,
      framework: pick(FRAMEWORK_POOL, seed),
      image: pick(IMAGE_POOL, seed),
      command: 'torchrun --nproc_per_node=8 train.py --config configs/default.yaml',
      currentStep,
      totalSteps,
      currentLoss: Number((0.5 + (seed % 10) * 0.07).toFixed(4)),
    });
  }
});

export const mockTrainingJobs: TrainingJob[] = jobs;
