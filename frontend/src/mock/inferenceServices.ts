import type { GpuType, InferenceService, JobStatus } from '@/types';
import { mockWorkspaces } from './workspaces';

const GPU_POOL: GpuType[] = ['A100', 'H100', 'g5.12xlarge'];
const STATUS_POOL: JobStatus[] = ['serving', 'pending', 'failed'];
const FRAMEWORK_POOL: InferenceService['framework'][] = ['vllm', 'sglang', 'trtllm'];
const MODEL_POOL = [
  'meta-llama/Llama-3.1-70B-Instruct',
  'Qwen/Qwen2.5-72B-Instruct',
  'mistralai/Mixtral-8x7B-Instruct-v0.1',
];

const pick = <T,>(arr: T[], idx: number): T => arr[idx % arr.length] as T;

const services: InferenceService[] = [];
mockWorkspaces.forEach((ws, wsIdx) => {
  for (let i = 0; i < 3; i += 1) {
    const seed = wsIdx * 10 + i;
    const status = pick(STATUS_POOL, seed);
    services.push({
      id: `inf-${ws.id}-${String(i + 1).padStart(3, '0')}`,
      workspaceId: ws.id,
      name: `${ws.name}-inf-${i + 1}`,
      status,
      framework: pick(FRAMEWORK_POOL, seed),
      modelRef: pick(MODEL_POOL, seed),
      gpuType: pick(GPU_POOL, seed),
      gpuCount: (seed % 4) + 2,
      replicas: (seed % 3) + 1,
      endpointUrl: `https://api.hyperpod.example.com/${ws.name}/inf-${i + 1}/v1`,
      qps: status === 'serving' ? 20 + seed * 3 : undefined,
      ttftMs: status === 'serving' ? 120 + seed * 5 : undefined,
    });
  }
});

export const mockInferenceServices: InferenceService[] = services;
