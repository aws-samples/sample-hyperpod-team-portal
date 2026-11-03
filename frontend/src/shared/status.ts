import type { BadgeProps } from 'antd';
import i18n from '@/shared/i18n';

/**
 * 任务原始 CR phase → status ns 里的 key (渲染时再翻译; 语言切换走整页刷新)。
 * 后端不再做 unified 归一; 各 CR 原始 phase 字符串直接展示。
 * 未命中映射 → 原样显示字符串 + default 灰 (新 phase 不至于报错)。
 */
const PHASE_LABEL_KEY = {
  // 训练 (含拼接, 命中关键字即可; 见 phaseColor 的 includes 逻辑)
  Pending: 'phase.pending',
  Running: 'phase.running',
  Succeeded: 'phase.succeeded',
  Completed: 'phase.succeeded',
  Failed: 'phase.failed',
  // 开发机
  Creating: 'phase.creating',
  Available: 'phase.running',
  Stopped: 'phase.stopped',
  Degraded: 'phase.degraded',
  // 推理
  DeploymentInProgress: 'phase.deploying',
  DeploymentPending: 'phase.pendingDeploy',
  DeploymentComplete: 'phase.running',
  InProgress: 'phase.deploying',
  Provisioning: 'phase.deploying',
} as const;

type PhaseKey = (typeof PHASE_LABEL_KEY)[keyof typeof PHASE_LABEL_KEY];
const label = (k: PhaseKey): string => i18n.t(k, { ns: 'status' });

export function phaseLabel(s: string | null | undefined): string {
  if (!s) return '-';
  // 1) 精确命中字典 (单值 phase, 如 "Available" / "DeploymentComplete")
  const exact = PHASE_LABEL_KEY[s as keyof typeof PHASE_LABEL_KEY];
  if (exact) return label(exact);
  // 2) 拼接态 (如 "Available/Progressing" / "Created/Running"): 按优先级关键字匹配,
  //    顺序与 phaseColor 对齐 (失败优先于运行, 防同串含多关键字误判)。
  if (/Fail/i.test(s)) return label('phase.failed');
  if (/Degraded|Error/i.test(s)) return label('phase.degraded');
  if (/Available|Running/i.test(s)) return label('phase.running');
  if (/Succeed/i.test(s)) return label('phase.succeeded');
  if (/Stopped/i.test(s)) return label('phase.stopped');
  if (/Creating/i.test(s)) return label('phase.creating');
  if (/Pending/i.test(s)) return label('phase.pending');
  if (/Provision|InProgress|Progressing/i.test(s)) return label('phase.deploying');
  // 3) 都不中: 原样显字符串 (新 phase 不至于报错)
  return s;
}

export function phaseColor(s: string | null | undefined): BadgeProps['status'] {
  const v = s ?? '';
  if (/Fail|Degraded|Error/i.test(v)) return 'error';
  if (/Succeed|Complete|Available|Running/i.test(v)) return 'success';
  if (/Pending|Provision|Progress|InProgress|Creating|Queued/i.test(v)) return 'processing';
  if (/Stopped/i.test(v)) return 'default';
  return 'default';
}

/**
 * kueue_status 六态 (Workload 字段镜像, informer 写) → Badge 颜色 (跨模块通用)。
 * 六态: Queued / QuotaReserved / Admitted / PodsReady / Evicted / Finished。
 * 文案不翻译: 直接显示 Workload 原始英文值 (调用方用 kueueStatusLabel 兜底空值 "-")。
 */
export function kueueStatusLabel(s: string | null | undefined): string | null {
  return s || null; // 原样返回; 空/未知 → null (调用方显 "-")
}

// 语义分色: 在等配额=warning黄 / 已拿配额启动中=processing蓝 / 运行中=success绿 / 结束=default灰。
const KUEUE_COLOR: Record<string, BadgeProps['status']> = {
  // 六态
  Queued: 'warning',
  Evicted: 'warning',
  QuotaReserved: 'processing',
  Admitted: 'processing',
  PodsReady: 'success',
  Finished: 'default',
  // 存量旧小写值兼容 (迁移期 DDB 可能仍有)
  queued: 'warning',
  started: 'processing',
  finished: 'default',
};

export function kueueStatusColor(s: string | null | undefined): BadgeProps['status'] {
  return KUEUE_COLOR[s ?? ''] ?? 'default';
}
