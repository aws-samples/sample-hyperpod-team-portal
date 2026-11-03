/* ============================================================================
 * Scheduling module mocks — mirrors Kueue ClusterQueue / Workload CRD schemas.
 *
 * These shapes deliberately track the backend `cluster_queue` /
 * `workload_snapshot` / `preemption_event` tables
 * so that wiring real Kueue data in M2 requires only swapping the datasource,
 * not rewriting the UI.
 * ========================================================================== */

export type JobType = 'training' | 'inference' | 'dev';
export type WorkloadPhase = 'Pending' | 'QuotaReserved' | 'Admitted' | 'Finished' | 'Preempted';
export type PreemptionPolicy = 'LowerPriority' | 'Any' | 'Never';

export interface ClusterQueueMock {
  id: string;
  name: string;
  display_name: string;
  cohort: string | null;
  preemption_policy: PreemptionPolicy;
  total_gpu: number;
  used_gpu: number;
  total_cpu_millicores: number;
  used_cpu_millicores: number;
  total_memory_mib: number;
  used_memory_mib: number;
  pending_workloads: number;
  admitted_workloads: number;
}

export interface WorkloadMock {
  id: string;
  cluster_queue_id: string;
  workload_name: string;
  workspace_name: string;
  creator_display_name: string;
  job_type: JobType;
  priority: number;
  /** GPU count */
  req_gpu: number;
  /** GPU SKU label, e.g. "A10G" / "H100" */
  req_gpu_type?: string;
  req_cpu_millicores: number;
  req_memory_mib: number;
  phase: WorkloadPhase;
  /** ISO-8601 timestamp when Kueue first saw the workload */
  pending_since: string;
}

export interface PreemptionEventMock {
  id: string;
  cluster_queue_id: string;
  preempting_workload: string;
  preempted_workload: string;
  reason: string;
  occurred_at: string;
  gpu_freed: number;
  /** semantic severity — drives Timeline dot color */
  severity: 'high-priority' | 'cohort-reclaim';
}

export interface AvgWaitPointMock {
  hour: string;
  training_minutes: number;
  inference_minutes: number;
}

/* ---------------- ClusterQueues (3) ---------------- */

export const MOCK_CLUSTER_QUEUES: ClusterQueueMock[] = [
  {
    id: 'cq-gpu-shared',
    name: 'gpu-shared',
    display_name: 'GPU Shared',
    cohort: 'platform-shared',
    preemption_policy: 'LowerPriority',
    total_gpu: 16,
    used_gpu: 8,
    total_cpu_millicores: 256_000,
    used_cpu_millicores: 128_000,
    total_memory_mib: 1_048_576,
    used_memory_mib: 524_288,
    pending_workloads: 6,
    admitted_workloads: 2,
  },
  {
    id: 'cq-cpu-only',
    name: 'cpu-only',
    display_name: 'CPU Only',
    cohort: 'platform-shared',
    preemption_policy: 'LowerPriority',
    total_gpu: 0,
    used_gpu: 0,
    total_cpu_millicores: 512_000,
    used_cpu_millicores: 240_000,
    total_memory_mib: 2_097_152,
    used_memory_mib: 786_432,
    pending_workloads: 2,
    admitted_workloads: 3,
  },
  {
    id: 'cq-p5-premium',
    name: 'p5-premium',
    display_name: 'P5 Premium',
    cohort: null,
    preemption_policy: 'Any',
    total_gpu: 8,
    used_gpu: 0,
    total_cpu_millicores: 192_000,
    used_cpu_millicores: 0,
    total_memory_mib: 786_432,
    used_memory_mib: 0,
    pending_workloads: 1,
    admitted_workloads: 0,
  },
];

/* ---------------- Workloads (12 pending items, spread across queues/priorities) ---------------- */

// Stamp `pending_since` relative to a frozen anchor so demo screenshots stay stable.
// Consumer code computes waiting duration against dayjs() at render — mock anchor
// is 2026-05-08T16:20 UTC so the first row lands ~15m back, the longest ~2h back.
const ANCHOR = '2026-05-08T16:20:00Z';
const anchorMs = Date.parse(ANCHOR);
const minsAgo = (m: number): string => new Date(anchorMs - m * 60_000).toISOString();

export const MOCK_WORKLOADS: WorkloadMock[] = [
  {
    id: 'w1',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'llama3-sft-01',
    workspace_name: 'team-a-nlp',
    creator_display_name: 'Alice Chen',
    job_type: 'training',
    priority: 200,
    req_gpu: 4,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 32_000,
    req_memory_mib: 131_072,
    phase: 'Pending',
    pending_since: minsAgo(8),
  },
  {
    id: 'w2',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'vit-pretrain-v2',
    workspace_name: 'team-b-cv',
    creator_display_name: 'Bob Wang',
    job_type: 'training',
    priority: 100,
    req_gpu: 2,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 16_000,
    req_memory_mib: 65_536,
    phase: 'Pending',
    pending_since: minsAgo(22),
  },
  {
    id: 'w3',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'qwen-72b-sft',
    workspace_name: 'team-a-nlp',
    creator_display_name: 'Alice Chen',
    job_type: 'training',
    priority: 100,
    req_gpu: 8,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 64_000,
    req_memory_mib: 262_144,
    phase: 'Pending',
    pending_since: minsAgo(45),
  },
  {
    id: 'w4',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'bert-infer-canary',
    workspace_name: 'team-c-recsys',
    creator_display_name: 'Carol Liu',
    job_type: 'inference',
    priority: 50,
    req_gpu: 1,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 4_000,
    req_memory_mib: 16_384,
    phase: 'Pending',
    pending_since: minsAgo(2),
  },
  {
    id: 'w5',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'stable-diffusion-xl',
    workspace_name: 'team-b-cv',
    creator_display_name: 'Diana Xu',
    job_type: 'inference',
    priority: 50,
    req_gpu: 2,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 8_000,
    req_memory_mib: 32_768,
    phase: 'Pending',
    pending_since: minsAgo(12),
  },
  {
    id: 'w6',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'rec-embed-train',
    workspace_name: 'team-c-recsys',
    creator_display_name: 'Ethan Zhao',
    job_type: 'training',
    priority: 0,
    req_gpu: 2,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 16_000,
    req_memory_mib: 65_536,
    phase: 'Pending',
    pending_since: minsAgo(55),
  },
  {
    id: 'w7',
    cluster_queue_id: 'cq-cpu-only',
    workload_name: 'data-prep-etl',
    workspace_name: 'team-a-nlp',
    creator_display_name: 'Alice Chen',
    job_type: 'training',
    priority: -10,
    req_gpu: 0,
    req_cpu_millicores: 8_000,
    req_memory_mib: 32_768,
    phase: 'Pending',
    pending_since: minsAgo(3),
  },
  {
    id: 'w8',
    cluster_queue_id: 'cq-cpu-only',
    workload_name: 'feature-pipeline-nightly',
    workspace_name: 'team-c-recsys',
    creator_display_name: 'Ethan Zhao',
    job_type: 'training',
    priority: 0,
    req_gpu: 0,
    req_cpu_millicores: 16_000,
    req_memory_mib: 65_536,
    phase: 'Pending',
    pending_since: minsAgo(18),
  },
  {
    id: 'w9',
    cluster_queue_id: 'cq-p5-premium',
    workload_name: 'emergency-retrain-prod',
    workspace_name: 'team-a-nlp',
    creator_display_name: 'Alice Chen',
    job_type: 'training',
    priority: 999,
    req_gpu: 8,
    req_gpu_type: 'H100',
    req_cpu_millicores: 96_000,
    req_memory_mib: 524_288,
    phase: 'Pending',
    pending_since: minsAgo(1),
  },
  {
    id: 'w10',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'yolo-retrain',
    workspace_name: 'team-b-cv',
    creator_display_name: 'Bob Wang',
    job_type: 'training',
    priority: 0,
    req_gpu: 2,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 16_000,
    req_memory_mib: 65_536,
    phase: 'Pending',
    pending_since: minsAgo(31),
  },
  {
    id: 'w11',
    cluster_queue_id: 'cq-gpu-shared',
    workload_name: 'llama3-infer-prod',
    workspace_name: 'team-a-nlp',
    creator_display_name: 'Alice Chen',
    job_type: 'inference',
    priority: 100,
    req_gpu: 4,
    req_gpu_type: 'A10G',
    req_cpu_millicores: 16_000,
    req_memory_mib: 131_072,
    phase: 'Pending',
    pending_since: minsAgo(6),
  },
  {
    id: 'w12',
    cluster_queue_id: 'cq-cpu-only',
    workload_name: 'log-compactor',
    workspace_name: 'team-c-recsys',
    creator_display_name: 'Carol Liu',
    job_type: 'training',
    priority: -20,
    req_gpu: 0,
    req_cpu_millicores: 4_000,
    req_memory_mib: 16_384,
    phase: 'Pending',
    pending_since: minsAgo(120),
  },
];

/* ---------------- Preemption events (6, newest first) ---------------- */

export const MOCK_PREEMPTION_EVENTS: PreemptionEventMock[] = [
  {
    id: 'p1',
    cluster_queue_id: 'cq-p5-premium',
    preempting_workload: 'emergency-retrain-prod',
    preempted_workload: 'qwen-72b-eval',
    reason: 'emergency priority (999) reclaims cohort',
    occurred_at: minsAgo(2),
    gpu_freed: 8,
    severity: 'high-priority',
  },
  {
    id: 'p2',
    cluster_queue_id: 'cq-gpu-shared',
    preempting_workload: 'llama3-sft-01',
    preempted_workload: 'vit-pretrain-v2',
    reason: 'higher-priority workload requires 4 GPU',
    occurred_at: minsAgo(18),
    gpu_freed: 4,
    severity: 'high-priority',
  },
  {
    id: 'p3',
    cluster_queue_id: 'cq-gpu-shared',
    preempting_workload: 'llama3-infer-prod',
    preempted_workload: 'rec-embed-train',
    reason: 'production inference reclaims resources',
    occurred_at: minsAgo(42),
    gpu_freed: 2,
    severity: 'high-priority',
  },
  {
    id: 'p4',
    cluster_queue_id: 'cq-cpu-only',
    preempting_workload: 'feature-pipeline-nightly',
    preempted_workload: 'log-compactor',
    reason: 'cohort reclaim — nightly ETL scheduled window',
    occurred_at: minsAgo(95),
    gpu_freed: 0,
    severity: 'cohort-reclaim',
  },
  {
    id: 'p5',
    cluster_queue_id: 'cq-gpu-shared',
    preempting_workload: 'bert-infer-canary',
    preempted_workload: 'yolo-retrain',
    reason: 'canary inference preempts background training',
    occurred_at: minsAgo(210),
    gpu_freed: 2,
    severity: 'cohort-reclaim',
  },
  {
    id: 'p6',
    cluster_queue_id: 'cq-gpu-shared',
    preempting_workload: 'stable-diffusion-xl',
    preempted_workload: 'yolo-retrain',
    reason: 'higher-priority inference job',
    occurred_at: minsAgo(320),
    gpu_freed: 2,
    severity: 'high-priority',
  },
];

/* ---------------- Average wait time (24 hourly points) ---------------- */

/**
 * Build a 24-point timeseries anchored to the mock anchor. Each entry is one
 * hour apart, t-23h to t-0. Values oscillate in plausible ranges
 * (training 2-8 min, inference 0.4-1.2 min) with a couple of synthetic
 * spikes to make the chart read as real ops data.
 */
export const MOCK_AVG_WAIT_TIME: AvgWaitPointMock[] = (() => {
  const points: AvgWaitPointMock[] = [];
  const trainingBase = [3.2, 4.1, 3.9, 5.0, 6.8, 7.5, 5.2, 4.0, 3.1, 2.8, 3.3, 4.4, 5.1, 5.8, 6.2, 5.5, 4.1, 3.6, 3.8, 4.5, 5.9, 7.2, 6.4, 4.8];
  const inferenceBase = [0.8, 0.7, 0.6, 0.9, 1.1, 1.0, 0.8, 0.6, 0.5, 0.5, 0.7, 0.8, 0.9, 1.0, 1.2, 1.0, 0.8, 0.6, 0.7, 0.8, 0.9, 1.1, 1.0, 0.7];
  for (let i = 0; i < 24; i += 1) {
    const hoursBack = 23 - i;
    points.push({
      hour: new Date(anchorMs - hoursBack * 3_600_000).toISOString(),
      training_minutes: trainingBase[i] ?? 4.0,
      inference_minutes: inferenceBase[i] ?? 0.8,
    });
  }
  return points;
})();
