"""i18n 守门 (贡献者指南见 docs/i18n-glossary.md §0)。

app/ (除 tests/) 下不得出现面向用户的中文字符串常量 —— 应走 app.core.i18n.t() 或改写英文。
豁免 (不报):
  - docstring 与裸字符串表达式语句 (属性文档串)
  - 日志调用参数: logger.* / log.* / logging.* / lg.*
  - 装饰器内的一切 (路由 summary / description / responses)
  - Field / Query / Path / Body / Header / APIRouter 调用的 description/title/summary/
    examples/example/deprecated 关键字参数 (OpenAPI 描述; 位置参数与 default 等不豁免)
  - 所在语句首行带 `# i18n-exempt` 注释 (须写原因, 如 `# i18n-exempt: openapi`)
    标记须写在语句首行 (多行 raise / 赋值即 raise 行 / 赋值行); 写在后续行不生效。
    与前端守门 (节点所在行) 规则不同。
  - app/main.py (OpenAPI tags / description) 与 app/locales/
用法: python scripts/check_i18n.py [--report] [--dump] [路径前缀...]
      前缀相对 services/platform-api, 如 app/modules/rayjob。--dump 输出 JSON (迁移前基线)。
计数按字符串常量片段 (f-string 每段各算一处), 非按句子。
退出码: 0 通过 / 1 有违规 / 2 用法错误、前缀无匹配、语法错误。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# CJK 标点 + 扩展A + 统一表意文字 + 全角形式 (与 frontend/scripts/check-i18n.mjs 一致)
CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")
EXEMPT_FILES = {"app/main.py"}
LOG_ROOTS = {"logger", "log", "logging", "lg"}
OPENAPI_CALLS = {"Field", "Query", "Path", "Body", "Header", "APIRouter"}
OPENAPI_KWARGS = {"description", "title", "summary", "examples", "example", "deprecated"}
MARKER = "i18n-exempt"
USAGE = "用法: python scripts/check_i18n.py [--report] [--dump] [路径前缀...]"


def _skipped_nodes(tree: ast.AST) -> set[int]:
    skip: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            skip.add(id(node.value))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                skip.update(id(n) for n in ast.walk(dec))
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name.split(".")[0] in LOG_ROOTS:
                skip.update(id(n) for n in ast.walk(node))
            elif name.split(".")[-1] in OPENAPI_CALLS:
                for kw in node.keywords:
                    if kw.arg in OPENAPI_KWARGS:
                        skip.update(id(n) for n in ast.walk(kw.value))
    return skip


def _marked(node: ast.AST, parents: dict[ast.AST, ast.AST], lines: list[str]) -> bool:
    cur = node
    while cur in parents and not isinstance(cur, ast.stmt):
        cur = parents[cur]
    return isinstance(cur, ast.stmt) and MARKER in lines[cur.lineno - 1]


def violations(source: str, filename: str = "<src>") -> list[tuple[int, str]]:
    """返回 [(行号, 去首尾空白的中文字符串)], 按行号排序。"""
    tree = ast.parse(source, filename)
    lines = source.splitlines()
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    skip = _skipped_nodes(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and CJK.search(node.value)
        ):
            continue
        if id(node) in skip or _marked(node, parents, lines):
            continue
        out.append((node.lineno, node.value.strip()))
    return sorted(out)


def iter_files(prefixes: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in sorted((ROOT / "app").rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if "/tests/" in rel or rel in EXEMPT_FILES or rel.startswith("app/locales/"):
            continue
        if prefixes and not any(rel.startswith(x) for x in prefixes):
            continue
        files.append(p)
    return files


def main(argv: list[str]) -> int:
    flags = {a for a in argv if a.startswith("-")}
    if flags - {"--report", "--dump"}:
        print(USAGE, file=sys.stderr)
        return 2
    prefixes = [a for a in argv if not a.startswith("-")]
    files = iter_files(prefixes)
    if prefixes and not files:
        print(f"❌ check_i18n: 前缀没有匹配到任何文件: {' '.join(prefixes)}", file=sys.stderr)
        return 2
    dump: list[dict[str, object]] = []
    total = 0
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        try:
            found = violations(p.read_text(encoding="utf-8-sig"), rel)
        except SyntaxError as e:
            print(f"❌ check_i18n: {rel} 语法错误 ({e.msg})", file=sys.stderr)
            return 2
        if not found:
            continue
        total += len(found)
        if "--dump" in flags:
            dump.extend({"file": rel, "line": ln, "text": tx} for ln, tx in found)
        elif "--report" in flags:
            print(f"{len(found):4d}  {rel}")
        else:
            for ln, tx in found:
                print(f"{rel}:{ln}  {tx[:60].replace(chr(10), '⏎')}")
    if "--dump" in flags:
        print(json.dumps(dump, ensure_ascii=False, indent=1))
        return 0
    if total:
        print(f"\n❌ check_i18n: 面向用户的硬编码中文 {total} 处")
        return 1
    print("✅ check_i18n: 无面向用户的硬编码中文")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
