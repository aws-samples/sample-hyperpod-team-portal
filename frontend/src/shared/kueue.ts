/** Kueue Workload 实时详情 (kueue-detail 端点返回; 不落库, 每次实时查)。 */

export interface KueueCondition {
  type?: string;
  status?: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

export interface KueueAdmission {
  clusterQueue?: string;
  // podSetAssignments[].resourceUsage 等; 结构来自 Kueue, 这里宽松接住
  [k: string]: unknown;
}

export interface KueueDetail {
  conditions: KueueCondition[];
  admission: KueueAdmission;
}
