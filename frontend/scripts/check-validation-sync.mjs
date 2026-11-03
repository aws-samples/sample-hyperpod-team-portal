/**
 * display_name 的 pattern 在后端 Pydantic (判定权) 与前端 antd rules (只做提示) 各有一份.
 * openapi-typescript 只生成类型不产出可用的正则字符串, 前端没法复用, 故不消除重复,
 * 只让重复无法悄悄漂移. 前置: 改过 Pydantic schema 先跑 `make api-sync`.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/** 后端 schema 名 ↔ 前端那份镜像 pattern 所在文件。新模块加一行即可。 */
const MODULES = [
  {
    module: '训练',
    schema: 'TrainingJobCreate',
    tsx: 'src/features/training/components/CreateForm/BasicSection.tsx',
  },
  {
    module: '推理',
    schema: 'InferenceCreate',
    tsx: 'src/features/inference/components/CreateForm/BasicSection.tsx',
  },
  {
    // 上限 20 而非 29 (Kueue label 长度所限), 故这条 pattern 与另两条本就不同
    module: '多机推理',
    schema: 'LlmdCreate',
    tsx: 'src/features/llmd/components/CreateForm/BasicSection.tsx',
  },
];

const OPENAPI_PATH = fileURLToPath(
  new URL('../../services/platform-api/openapi.json', import.meta.url),
);

function fail(lines) {
  console.error('check-validation-sync: 前后端校验规则不一致\n');
  for (const l of lines) if (l) console.error(`  ${l}`);
  console.error('');
  process.exit(1);
}

let spec;
try {
  spec = JSON.parse(readFileSync(OPENAPI_PATH, 'utf8'));
} catch (e) {
  fail([`读不到 openapi.json: ${e.message}`, '先跑 `make api-export`。']);
}

for (const { module, schema, tsx: relTsx } of MODULES) {
  const backendPattern =
    spec?.components?.schemas?.[schema]?.properties?.display_name?.pattern;

  if (!backendPattern) {
    fail([
      `[${module}] openapi.json 里找不到 ${schema}.display_name.pattern。`,
      `要么后端删了这条 pattern (${relTsx} 那份也该删), 要么 openapi.json 过期 (跑 \`make api-sync\`)。`,
    ]);
  }

  const tsx = readFileSync(
    fileURLToPath(new URL(`../${relTsx}`, import.meta.url)),
    'utf8',
  );
  const found = [...tsx.matchAll(/pattern:\s*\/(.+?)\/[gimsuy]*\s*,/g)].map(
    (m) => m[1],
  );

  if (found.length !== 1) {
    fail([
      `[${module}] ${relTsx} 里找到 ${found.length} 条 pattern 字面量, 期望 1 条。`,
      '本脚本按"只有 display_name 一条"设计; 新增别的 pattern 请同步改本脚本。',
      found.length ? `找到: ${found.map((f) => `/${f}/`).join('  ')}` : '',
    ]);
  }

  if (found[0] !== backendPattern) {
    fail([
      `[${module}] 后端 (openapi.json ${schema}): /${backendPattern}/`,
      `[${module}] 前端 (${relTsx}): /${found[0]}/`,
      '',
      '判定权在后端, 请把前端那条改成逐字符一致 (它只是提示, 不要自行放宽或收紧)。',
      '若后端刚改过 pattern 但没导出契约, 先跑 `make api-sync`。',
    ]);
  }

  console.log(
    `check-validation-sync: [${module}] display_name pattern 一致 (/${backendPattern}/)`,
  );
}
