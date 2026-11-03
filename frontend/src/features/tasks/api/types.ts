export type TaskKind = 'dev' | 'train' | 'inference' | 'dynamo' | 'llmd' | 'rayjob';

export interface TaskStats {
  running_starting: number;
  queued: number;
}

export interface TaskRow {
  id: string;
  kind: TaskKind;
  name: string | null;
  k8s_name: string | null; // CR name (= cr_name, 改优先级调 priority 模块端点用)
  status: string | null; // 原始 CR phase 字符串 (不再 unified)
  kueue_status: string | null; // Kueue 六态 Queued/QuotaReserved/Admitted/PodsReady/Evicted/Finished (Workload镜像)
  creator: string | null;
  priority_class: string | null;
  priority_value: number | null; // WPC 数值 rank (无/未知 → null)
  gpu_spec: string;
  created_at: string | null;
  started_at: string | null;
}

export interface TaskOverviewResponse {
  can_edit_priority: boolean;
  stats: TaskStats;
  tasks: TaskRow[];
}

/** 单个排队 Workload 明细 (原始透传, 展开可查)。 */
export interface QueueWorkload {
  name: string;
  position: number; // 0-based, Kueue LocalQueue 绝对身位
  priority: number; // Kueue Workload spec.priority (WPC 值; 无 → 0)
}

/** 一个任务的排队信息: 主身位 (min) + 全部 Workload 明细。 */
export interface QueueEntry {
  position: number; // min(workloads.position), 0-based
  workloads: QueueWorkload[];
}
