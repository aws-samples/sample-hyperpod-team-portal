/**
 * 任务名 (K8s 资源名) 生成工具。
 *
 * 任务名 = sanitize(显示名) + '-' + 10 位随机后缀, 必须全局唯一:
 * k8s / kueue 层面唯一, 且日志按它做 log stream prefix。
 * 后端 (create.py) 直接采用前端派生的 name、不再加后缀也不查重, 唯一性全靠这个随机后缀,
 * 故任务名字段在表单里只读展示、克隆时必须重新生成 (见各 BasicSection / CreateForm)。
 */

/** 显示名 → DNS-safe 前缀 (小写, 非[a-z0-9]→-, 压缩/去首尾-, 字母开头, ≤52)。 */
export function toDnsLabel(text: string): string {
  let s = (text || '').trim().toLowerCase();
  s = s.replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-+|-+$/g, '');
  if (s && !/^[a-z]/.test(s)) s = `t-${s}`;
  return s.slice(0, 52).replace(/-+$/, '');
}

/** 10 位随机 a-z0-9 后缀, 保证任务名唯一。 */
export function randomSuffix(): string {
  const a = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < 10; i++) s += a[Math.floor(Math.random() * a.length)];
  return s;
}

/** 由显示名生成完整任务名 (sanitize 前缀 + 随机后缀); 显示名清洗后为空则返回空串。 */
export function buildTaskName(displayName: string): string {
  const prefix = toDnsLabel(displayName);
  return prefix ? `${prefix}-${randomSuffix()}` : '';
}
