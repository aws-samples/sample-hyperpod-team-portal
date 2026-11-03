/**
 * Wave 5 (P0-4) · 前端 import 规则守门 (替代 ESLint no-restricted-imports).
 *
 * 禁止 import 路径:
 * 1. `@/components/*`         (已迁 shared/ui · 整目录已删)
 * 2. `@/api/{client,cluster,dev-instance,quota,training,workspace}`
 *    (已迁 features/<X>/api · shim 已删)
 *
 * 例外白名单:
 * - `@/api/{logs,monitoring,user}` 暂留 (对应 feature 还没拆出,
 *   建 features/<name>/api/ 后请同步迁走并从本文件白名单删除)
 *
 * 触发: 出现违规直接 process.exit(1), CI 拒绝合并.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../src', import.meta.url));
const SUFFIXES = ['.ts', '.tsx'];
const SKIP_DIRS = new Set(['node_modules', 'dist', '__pycache__']);

// 严格禁止的 import 前缀 + 提示文字
const BANNED = [
  {
    pattern: /from\s+['"]@\/components\//,
    message:
      "@/components/* 已迁 @/shared/ui/ (Wave 5 P0-4). " +
      "metrics 改 @/shared/ui/metrics/, common 改 @/shared/ui/.",
  },
  {
    pattern:
      /from\s+['"]@\/api\/(client|cluster|dev-instance|quota|training|workspace)['"]/,
    message:
      "@/api/{client,cluster,dev-instance,quota,training,workspace} 已迁 @/features/<X>/api/ " +
      "(Wave 5 P0-4). 例: @/features/workspace/api, @/features/quota/api, " +
      "@/features/admin/api/cluster, @/features/devinstance/api/client.",
  },
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue;
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      yield* walk(full);
    } else if (SUFFIXES.some((s) => name.endsWith(s))) {
      yield full;
    }
  }
}

const violations = [];
for (const file of walk(ROOT)) {
  const text = readFileSync(file, 'utf8');
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const { pattern, message } of BANNED) {
      if (pattern.test(line)) {
        violations.push({
          file: relative(process.cwd(), file),
          line: i + 1,
          text: line.trim(),
          message,
        });
      }
    }
  }
}

if (violations.length === 0) {
  console.log('✅ check-imports: 无违规 (扫描根 frontend/src)');
  process.exit(0);
}

console.error(`❌ check-imports: 发现 ${violations.length} 处违规\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line}  ${v.text}`);
  console.error(`    → ${v.message}\n`);
}
process.exit(1);
