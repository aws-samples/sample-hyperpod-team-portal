/**
 * 资源池 (CPU/GPU) 派生工具 · 开发机/训练/推理 三模块共用。
 * 机型的 pool 由后端 quota.resources[].pool 给出 (后端 EC2 GpuInfo 权威判);
 * 模板按 resource.gpu 派生。
 */
export type Pool = 'cpu' | 'gpu';

/** 模板属哪池: resource.gpu > 0 = GPU, == 0 = CPU。 */
export function poolOfTemplate(t: { resource: { gpu: number } }): Pool {
  return (t.resource?.gpu ?? 0) > 0 ? 'gpu' : 'cpu';
}

/**
 * 模板在所选资源池下是否可选 (2026-06-25 确定, 开发机/训练/推理一致):
 * - GPU 池: 不筛选, 全部模板可选 (CPU 模板也能调度到 GPU 节点上跑);
 * - CPU 池: 只显示无 GPU 的模板 (gpu == 0)。
 */
export function templateInPool(
  t: { resource: { gpu: number } },
  pool: Pool,
): boolean {
  return pool === 'gpu' ? true : (t.resource?.gpu ?? 0) === 0;
}

export const POOL_LABEL: Record<Pool, string> = { gpu: 'GPU', cpu: 'CPU' };

export const POOL_OPTIONS: { label: string; value: Pool }[] = [
  { label: 'GPU', value: 'gpu' },
  { label: 'CPU', value: 'cpu' },
];
