#!/usr/bin/env node
/**
 * i18n 守门 (贡献者指南见 docs/i18n-glossary.md §0)。
 *
 * 规则 1 硬编码中文: 从 src/main.tsx 出发 import 可达的 .ts/.tsx 中, 字符串字面量 / 模板字符串
 *   片段 / JSX 文本不得含中文 (CJK 统一表意 + 扩展A + CJK 标点 + 全角形式; TypeScript AST 判定, 注释天然不在其中)。不可达文件 (死代码) 不查。
 *   豁免: src/shared/i18n/locales/**、src/features/docs/pages/zh-CN/**、schema.gen.ts、*.d.ts,
 *   以及所在行带 `i18n-exempt` 注释的节点 (须写原因, 如 `// i18n-exempt: 语言自称`)。
 *   `i18n-exempt` 须写在中文节点起始所在的同一行 (上一行的注释不生效), 该行内所有中文节点一并豁免。
 * 规则 2 文案表一致: locales/zh-CN 与 en-US 的 ns 文件集合、key 集合 (忽略 i18next 复数后缀)、
 *   同 key 的 {{占位符}} 集合必须一致; en-US 的值不得含中文 (common.json 的 language.* 除外)。
 *
 * 用法: node scripts/check-i18n.mjs [--report] [--dump-cjk] [前缀...]
 *   前缀: 只查 src/ 下以此开头的文件 (如 features/training); 规则 2 始终全量。
 *   --report: 只打印每文件违规数。 --dump-cjk: 打印全部中文节点 JSON (迁移前基线), 不做检查。
 *   环境变量 I18N_SRC 可指向别的 src 目录 (自测用)。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(process.env.I18N_SRC ?? path.join(HERE, '../src'));
const LOCALES = path.join(SRC, 'shared/i18n/locales');
const CJK = /[\u3000-\u303F\u3400-\u4DBF\u4E00-\u9FFF\uFF00-\uFFEF]/;
const EXEMPT_PREFIXES = ['shared/i18n/locales/', 'features/docs/pages/zh-CN/'];
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;
const PLACEHOLDER = /\{\{[-\s]*([\w.]+)\s*(?:,[^}]*)?\}\}/g;
const RESOLVE_EXTS = ['', '.ts', '.tsx', '/index.ts', '/index.tsx'];
const STRING_KINDS = new Set([
  ts.SyntaxKind.StringLiteral,
  ts.SyntaxKind.NoSubstitutionTemplateLiteral,
  ts.SyntaxKind.TemplateHead,
  ts.SyntaxKind.TemplateMiddle,
  ts.SyntaxKind.TemplateTail,
  ts.SyntaxKind.JsxText,
]);

const argv = process.argv.slice(2);
const flags = new Set(argv.filter((a) => a.startsWith('--')));
const prefixes = argv.filter((a) => !a.startsWith('--'));
const KNOWN_FLAGS = new Set(['--report', '--dump-cjk']);
if ([...flags].some((f) => !KNOWN_FLAGS.has(f))) {
  console.error('用法: node scripts/check-i18n.mjs [--report] [--dump-cjk] [前缀...]');
  process.exit(2);
}

function parse(file) {
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, kind);
}

function resolveImport(from, spec) {
  let base;
  if (spec.startsWith('@/')) base = path.join(SRC, spec.slice(2));
  else if (spec.startsWith('.')) base = path.resolve(path.dirname(from), spec);
  else return null;
  base = base.replace(/\?raw$/, '');
  for (const ext of RESOLVE_EXTS) {
    const p = base + ext;
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  }
  return null;
}

/** 从 main.tsx 沿 import / export-from / 动态 import() 收集可达的 .ts/.tsx。 */
function reachableFiles() {
  const seen = new Set();
  const stack = [path.join(SRC, 'main.tsx')];
  while (stack.length) {
    const file = stack.pop();
    if (seen.has(file) || !/\.(ts|tsx)$/.test(file)) continue;
    seen.add(file);
    const visit = (node) => {
      let spec;
      if (
        (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
        node.moduleSpecifier &&
        ts.isStringLiteral(node.moduleSpecifier)
      ) {
        spec = node.moduleSpecifier.text;
      } else if (
        ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword &&
        node.arguments[0] &&
        ts.isStringLiteral(node.arguments[0])
      ) {
        spec = node.arguments[0].text;
      }
      if (spec) {
        const r = resolveImport(file, spec);
        if (r) stack.push(r);
      }
      ts.forEachChild(node, visit);
    };
    visit(parse(file));
  }
  return [...seen];
}

function cjkNodes(file) {
  const sf = parse(file);
  const lines = sf.text.split('\n');
  const out = [];
  const visit = (node) => {
    if (STRING_KINDS.has(node.kind)) {
      const text = node.kind === ts.SyntaxKind.JsxText ? node.getText(sf) : node.text;
      if (CJK.test(text)) {
        const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line;
        if (!lines[line].includes('i18n-exempt')) out.push({ line: line + 1, text: text.trim() });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

const relOf = (file) => path.relative(SRC, file).split(path.sep).join('/');
const isExempt = (rel) =>
  rel.endsWith('.d.ts') || rel.endsWith('schema.gen.ts') || EXEMPT_PREFIXES.some((p) => rel.startsWith(p));

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') flatten(v, key, out);
    else out[key] = String(v);
  }
  return out;
}

function groupByBase(flat) {
  const m = new Map();
  for (const [k, v] of Object.entries(flat)) {
    const base = k.replace(PLURAL_SUFFIX, '');
    if (!m.has(base)) m.set(base, []);
    m.get(base).push(v);
  }
  return m;
}

function placeholdersOf(values) {
  const s = new Set();
  for (const v of values) for (const m of v.matchAll(PLACEHOLDER)) s.add(m[1]);
  return [...s].sort().join(',');
}

function checkLocales() {
  const errors = [];
  const list = (lng) => {
    const d = path.join(LOCALES, lng);
    return fs.existsSync(d) ? fs.readdirSync(d).filter((f) => f.endsWith('.json')).sort() : [];
  };
  const zhFiles = list('zh-CN');
  const enFiles = list('en-US');
  if (!zhFiles.length) errors.push('locales/zh-CN 不存在或没有 .json');
  if (!enFiles.length) errors.push('locales/en-US 不存在或没有 .json');
  for (const f of [...new Set([...zhFiles, ...enFiles])].sort()) {
    if (!zhFiles.includes(f) || !enFiles.includes(f)) {
      errors.push(`${f}: 只存在于 ${zhFiles.includes(f) ? 'zh-CN' : 'en-US'}`);
      continue;
    }
    const load = (lng) => {
      try {
        return groupByBase(flatten(JSON.parse(fs.readFileSync(path.join(LOCALES, lng, f), 'utf8'))));
      } catch (e) {
        errors.push(`${lng}/${f}: JSON 解析失败 (${e.message})`);
        return null;
      }
    };
    const zh = load('zh-CN');
    const en = load('en-US');
    if (!zh || !en) continue;
    for (const k of zh.keys()) if (!en.has(k)) errors.push(`${f}: en-US 缺 ${k}`);
    for (const k of en.keys()) if (!zh.has(k)) errors.push(`${f}: zh-CN 缺 ${k}`);
    for (const [k, zv] of zh) {
      const ev = en.get(k);
      if (!ev) continue;
      const pz = placeholdersOf(zv);
      const pe = placeholdersOf(ev);
      if (pz !== pe) errors.push(`${f}: ${k} 占位符不一致 zh={${pz}} en={${pe}}`);
      const selfName = f === 'common.json' && k.startsWith('language.');
      if (!selfName && ev.some((v) => CJK.test(v))) errors.push(`${f}: en-US ${k} 含中文 (未翻译?)`);
    }
  }
  return errors;
}

function main() {
  const entry = path.join(SRC, 'main.tsx');
  if (!fs.existsSync(entry)) {
    console.log(`❌ check-i18n: 找不到入口 ${entry} (检查 I18N_SRC)`);
    process.exit(1);
  }
  const files = reachableFiles()
    .map((f) => ({ f, rel: relOf(f) }))
    .filter(({ rel }) => !isExempt(rel))
    .filter(({ rel }) => prefixes.length === 0 || prefixes.some((p) => rel.startsWith(p)))
    .sort((a, b) => a.rel.localeCompare(b.rel));

  if (flags.has('--dump-cjk')) {
    const all = [];
    for (const { f, rel } of files) for (const n of cjkNodes(f)) all.push({ file: rel, ...n });
    process.stdout.write(`${JSON.stringify(all, null, 1)}\n`);
    return;
  }

  let total = 0;
  for (const { f, rel } of files) {
    const nodes = cjkNodes(f);
    if (!nodes.length) continue;
    total += nodes.length;
    if (flags.has('--report')) console.log(`${String(nodes.length).padStart(4)}  ${rel}`);
    else for (const n of nodes) console.log(`${rel}:${n.line}  ${n.text.slice(0, 60)}`);
  }
  const localeErrors = checkLocales();
  for (const e of localeErrors) console.log(`[locales] ${e}`);
  if (total || localeErrors.length) {
    console.log(`\n❌ check-i18n: 硬编码中文 ${total} 处, 文案表问题 ${localeErrors.length} 处`);
    process.exit(1);
  }
  console.log('✅ check-i18n: 无硬编码中文, 文案表一致');
}

main();
